// Exports facts for explicitly mapped functions in an owned stripped fixture.
// @category IRVeil
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

import com.google.gson.*;
import ghidra.app.decompiler.*;
import ghidra.app.util.headless.HeadlessScript;
import ghidra.framework.Application;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.pcode.*;

public class ExportDecompilation extends HeadlessScript {
    private static final int MAX_FUNCTIONS = 32;
    private static final int MAX_C_BYTES = 262144;
    private static final int MAX_PCODE_BYTES = 1048576;
    private static final int MAX_OPERATIONS = 100000;

    private void write(Path path, String text) throws IOException {
        Files.writeString(path, text, StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW);
    }

    private void increment(Map<String, Integer> histogram, String key) {
        histogram.put(key, histogram.getOrDefault(key, 0) + 1);
    }

    private Map<String, Object> exportFunction(JsonObject spec, Path output, DecompInterface decompiler, int timeout) throws Exception {
        String id = spec.get("id").getAsString();
        if (!id.matches("re_[a-z0-9_]+")) throw new IOException("Invalid logical function identifier");
        Address entry = toAddr(spec.get("address").getAsString());
        Map<String, Object> record = new LinkedHashMap<>();
        record.put("id", id);
        record.put("requestedAddress", entry.toString());
        record.put("companionSymbolBytes", spec.get("size").getAsLong());
        Function function = currentProgram.getFunctionManager().getFunctionAt(entry);
        record.put("functionOrigin", "auto_analysis");
        // Known entry locations are an explicit experimental input. A trivial
        // function can lose all call references after optimization and therefore
        // be absent from automatic function discovery in the stripped program.
        if (function == null) {
            disassemble(entry);
            function = createFunction(entry, null);
            record.put("functionOrigin", "companion_entry");
        }
        if (function == null) { record.put("status", "missing_function"); return record; }
        record.put("entryAddress", function.getEntryPoint().toString());
        record.put("ghidraName", function.getName());
        record.put("bodyAddressBytes", function.getBody().getNumAddresses());
        Map<String, Integer> rawHistogram = new TreeMap<>();
        int nativeCount = 0;
        long nativeBytes = 0;
        int rawCount = 0;
        int nativeCalls = 0;
        int nativeJumps = 0;
        InstructionIterator listing = currentProgram.getListing().getInstructions(function.getBody(), true);
        while (listing.hasNext()) {
            monitor.checkCancelled();
            Instruction instruction = listing.next();
            if (++nativeCount > MAX_OPERATIONS) throw new IOException("Native instruction export bound exceeded");
            nativeBytes += instruction.getLength();
            if (instruction.getFlowType().isCall()) nativeCalls++;
            if (instruction.getFlowType().isJump()) nativeJumps++;
            for (PcodeOp operation : instruction.getPcode()) {
                if (++rawCount > MAX_OPERATIONS) throw new IOException("Raw P-code export bound exceeded");
                increment(rawHistogram, operation.getMnemonic());
            }
        }
        record.put("nativeInstructions", nativeCount);
        record.put("nativeInstructionBytes", nativeBytes);
        record.put("nativeCalls", nativeCalls);
        record.put("nativeJumps", nativeJumps);
        record.put("rawPcodeOperations", rawCount);
        record.put("rawPcodeHistogram", rawHistogram);

        DecompileResults result = decompiler.decompileFunction(function, timeout, monitor);
        record.put("timedOut", result.isTimedOut());
        record.put("cancelled", result.isCancelled());
        record.put("diagnostic", result.getErrorMessage());
        if (!result.decompileCompleted() || result.getDecompiledFunction() == null || result.getHighFunction() == null) {
            record.put("status", "decompile_failed"); return record;
        }
        String c = result.getDecompiledFunction().getC();
        if (c.getBytes(StandardCharsets.UTF_8).length > MAX_C_BYTES) throw new IOException("Decompiled C export bound exceeded");
        HighFunction high = result.getHighFunction();
        Map<String, Integer> highHistogram = new TreeMap<>();
        StringBuilder pcode = new StringBuilder();
        int highCount = 0;
        Iterator<PcodeOpAST> operations = high.getPcodeOps();
        while (operations.hasNext()) {
            monitor.checkCancelled();
            PcodeOpAST operation = operations.next();
            if (++highCount > MAX_OPERATIONS) throw new IOException("High P-code operation bound exceeded");
            increment(highHistogram, operation.getMnemonic());
            pcode.append(operation.toString()).append('\n');
            if (pcode.length() > MAX_PCODE_BYTES / 4) throw new IOException("High P-code text bound exceeded");
        }
        int edges = 0;
        for (PcodeBlockBasic block : high.getBasicBlocks()) edges += block.getOutSize();
        String cFile = id + ".c";
        String pcodeFile = id + ".pcode.txt";
        write(output.resolve(cFile), c);
        write(output.resolve(pcodeFile), pcode.toString());
        record.put("cFile", cFile);
        record.put("pcodeFile", pcodeFile);
        record.put("cUtf8Bytes", c.getBytes(StandardCharsets.UTF_8).length);
        record.put("highPcodeOperations", highCount);
        record.put("highPcodeHistogram", highHistogram);
        record.put("highBasicBlocks", high.getBasicBlocks().size());
        record.put("highEdges", edges);
        record.put("status", result.isTimedOut() || result.isCancelled() ? "decompile_incomplete" : "completed");
        return record;
    }

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 3) throw new IOException("Expected manifest path, output directory and decompilation timeout");
        Path manifestPath = Paths.get(args[0]).toAbsolutePath().normalize();
        Path output = Paths.get(args[1]).toAbsolutePath().normalize();
        Files.createDirectories(output);
        Map<String, Object> report = new LinkedHashMap<>();
        List<Map<String, Object>> functions = new ArrayList<>();
        report.put("schemaVersion", 1);
        report.put("status", "incomplete");
        report.put("functions", functions);
        report.put("ghidraVersion", Application.getApplicationVersion());
        report.put("javaVersion", System.getProperty("java.version"));
        report.put("jvmMaxHeapBytes", Runtime.getRuntime().maxMemory());
        report.put("availableProcessors", Runtime.getRuntime().availableProcessors());
        report.put("userHome", System.getProperty("user.home"));
        DecompInterface decompiler = new DecompInterface();
        try {
            if (Files.size(manifestPath) > 65536) throw new IOException("Manifest exceeds 64 KiB");
            JsonObject manifest = JsonParser.parseString(Files.readString(manifestPath)).getAsJsonObject();
            int timeout = Integer.parseInt(args[2]);
            if (timeout < 1 || timeout > 30) throw new IOException("Decompilation timeout must be 1..30 seconds");
            JsonArray requested = manifest.getAsJsonArray("functions");
            if (requested.size() < 1 || requested.size() > MAX_FUNCTIONS) throw new IOException("Selected function count out of bounds");
            boolean analysisTimedOut = analysisTimeoutOccurred();
            report.put("analysisTimedOut", analysisTimedOut);
            report.put("binarySha256", currentProgram.getExecutableSHA256());
            report.put("expectedBinarySha256", manifest.get("binarySha256").getAsString());
            report.put("language", currentProgram.getLanguageID().toString());
            report.put("compilerSpec", currentProgram.getCompilerSpec().getCompilerSpecID().toString());
            report.put("imageBase", currentProgram.getImageBase().toString());
            if (!manifest.get("binarySha256").getAsString().equalsIgnoreCase(currentProgram.getExecutableSHA256())) throw new IOException("Imported binary hash differs from manifest");
            if (analysisTimedOut) throw new IOException("Ghidra auto-analysis timed out");
            if (Runtime.getRuntime().maxMemory() > 1073741824L || Runtime.getRuntime().availableProcessors() > 2) throw new IOException("Headless resource profile not enforced");
            if (!decompiler.setSimplificationStyle("decompile") || !decompiler.toggleCCode(true) || !decompiler.toggleSyntaxTree(true)) throw new IOException("Decompiler configuration failed");
            if (!decompiler.openProgram(currentProgram)) throw new IOException("Decompiler could not open the imported program");
            boolean complete = true;
            for (JsonElement element : requested) {
                Map<String, Object> function;
                try { function = exportFunction(element.getAsJsonObject(), output, decompiler, timeout); }
                catch (Exception error) {
                    function = new LinkedHashMap<>();
                    function.put("id", element.getAsJsonObject().get("id").getAsString());
                    function.put("status", "export_failed");
                    function.put("error", error.toString());
                }
                if (!"completed".equals(function.get("status"))) complete = false;
                functions.add(function);
            }
            report.put("status", complete ? "completed" : "incomplete");
        } catch (Exception error) { report.put("error", error.toString()); }
        finally {
            decompiler.dispose();
            write(output.resolve("export.json"), new GsonBuilder().setPrettyPrinting().create().toJson(report) + "\n");
        }
        println("IRVeil export status: " + report.get("status"));
    }
}
