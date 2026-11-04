// Exports bounded pure return slices from Ghidra's SSA high P-code.
// @category IRVeil
import java.io.IOException;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import com.google.gson.*;
import ghidra.app.decompiler.*;
import ghidra.app.util.headless.HeadlessScript;
import ghidra.framework.Application;
import ghidra.program.model.listing.*;
import ghidra.program.model.pcode.*;

public class ExportExpressions extends HeadlessScript {
    private int nodes;
    private int maxNodes = 512;
    private int maxExpressionBytes = 16384;
    private final Set<Varnode> active = Collections.newSetFromMap(new IdentityHashMap<>());
    private final Set<Integer> parameters = new TreeSet<>();

    private void writeReport(Path output, Map<String,Object> report) throws IOException {
        Files.writeString(output, new GsonBuilder().setPrettyPrinting().create().toJson(report) + "\n",
                          StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW);
    }

    private String slice(Varnode value, int width, int depth) throws IOException {
        if (++nodes > maxNodes || depth > 64) throw new IOException("slice node/depth bound");
        if (value.getSize() * 8 != width) throw new IOException("mixed-width slice");
        if (value.isConstant()) {
            return new BigInteger(Long.toUnsignedString(value.getOffset())).and(
                BigInteger.ONE.shiftLeft(width).subtract(BigInteger.ONE)).toString();
        }
        PcodeOp definition = value.getDef();
        if (definition == null) {
            HighVariable high = ((VarnodeAST)value).getHigh();
            if (!(high instanceof HighParam)) throw new IOException("non-parameter leaf");
            int slot = ((HighParam)high).getSlot();
            if (slot < 0 || slot > 3) throw new IOException("parameter bound");
            parameters.add(slot);
            return "p" + slot;
        }
        // Storage addresses repeat after register assignments. Follow SSA defs,
        // never reconstruct dependencies from the human-readable P-code text.
        if (!active.add(value)) throw new IOException("cyclic slice");
        try {
            int opcode = definition.getOpcode();
            String a = slice(definition.getInput(0), width, depth + 1);
            if (opcode == PcodeOp.COPY) return a;
            if (opcode == PcodeOp.INT_NEGATE) return "(~(" + a + "))";
            if (opcode == PcodeOp.INT_2COMP) return "(-(" + a + "))";
            if (opcode == PcodeOp.INT_LEFT) {
                Varnode shift = definition.getInput(1);
                if (!shift.isConstant() || shift.getOffset() < 0 || shift.getOffset() >= width)
                    throw new IOException("nonconstant/out-of-range shift");
                return "((" + a + ")*" + BigInteger.ONE.shiftLeft((int)shift.getOffset()) + ")";
            }
            String operator;
            switch (opcode) {
                case PcodeOp.INT_ADD: operator = "+"; break;
                case PcodeOp.INT_SUB: operator = "-"; break;
                case PcodeOp.INT_MULT: operator = "*"; break;
                case PcodeOp.INT_AND: operator = "&"; break;
                case PcodeOp.INT_OR: operator = "|"; break;
                case PcodeOp.INT_XOR: operator = "^"; break;
                default: throw new IOException("unsupported P-code " + definition.getMnemonic());
            }
            String b = slice(definition.getInput(1), width, depth + 1);
            String expression = "(" + a + operator + b + ")";
            if (expression.length() > maxExpressionBytes) throw new IOException("expression byte bound");
            return expression;
        } finally { active.remove(value); }
    }

    private Map<String,Object> extract(JsonObject spec, DecompInterface decompiler) throws Exception {
        Map<String,Object> record = new LinkedHashMap<>();
        String id = spec.get("id").getAsString();
        record.put("id", id);
        Function function = currentProgram.getFunctionManager().getFunctionAt(toAddr(spec.get("address").getAsString()));
        if (function == null) {
            disassemble(toAddr(spec.get("address").getAsString()));
            function = createFunction(toAddr(spec.get("address").getAsString()), null);
        }
        if (function == null) throw new IOException("missing function " + id);
        int instructions = 0, bytes = 0;
        InstructionIterator listing = currentProgram.getListing().getInstructions(function.getBody(), true);
        while (listing.hasNext()) {
            Instruction instruction = listing.next();
            if (++instructions > 100000) throw new IOException("native instruction bound");
            bytes += instruction.getLength();
        }
        record.put("nativeInstructions", instructions);
        record.put("nativeBytes", bytes);
        DecompileResults result = decompiler.decompileFunction(function, 30, monitor);
        if (result.isTimedOut()) {
            record.put("status", "timeout");
            record.put("stage", "ghidra_decompilation");
            record.put("reason", "Ghidra decompilation exceeded 30-second deadline");
            return record;
        }
        if (!result.decompileCompleted() || result.isCancelled() || result.getHighFunction() == null)
            throw new IOException("decompilation failed: " + result.getErrorMessage());
        HighFunction high = result.getHighFunction();
        record.put("c", result.getDecompiledFunction().getC());
        try {
            if (high.getBasicBlocks().size() != 1) throw new IOException("control flow (multiple blocks)");
            PcodeOp returned = null;
            int count = 0;
            Iterator<PcodeOpAST> operations = high.getPcodeOps();
            while (operations.hasNext()) {
                PcodeOpAST operation = operations.next();
                if (++count > 100000) throw new IOException("high P-code operation bound");
                if (operation.getOpcode() == PcodeOp.RETURN) {
                    if (returned != null) throw new IOException("multiple returns");
                    returned = operation;
                }
                if (operation.getOpcode() == PcodeOp.STORE || operation.getOpcode() == PcodeOp.CALL ||
                    operation.getOpcode() == PcodeOp.CALLIND || operation.getOpcode() == PcodeOp.CALLOTHER)
                    throw new IOException("side effect/call");
            }
            if (returned == null || returned.getNumInputs() != 2) throw new IOException("no scalar return");
            int width = returned.getInput(1).getSize() * 8;
            if (width != 32 && width != 64) throw new IOException("unsupported return width");
            nodes = 0; active.clear(); parameters.clear();
            record.put("expression", slice(returned.getInput(1), width, 0));
            record.put("width", width);
            record.put("parameters", new ArrayList<>(parameters));
            record.put("sliceNodes", nodes);
            record.put("status", "extracted");
        } catch (IOException unsupported) {
            record.put("status", "unsupported");
            record.put("reason", unsupported.getMessage());
        }
        return record;
    }

    @Override protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 3) throw new IOException("Expected manifest, output file and extraction profile");
        if (args[2].equals("expanded")) { maxNodes = 4096; maxExpressionBytes = 131072; }
        else if (!args[2].equals("primary")) throw new IOException("unknown extraction profile");
        if (Files.size(Paths.get(args[0])) > 65536) throw new IOException("manifest bound");
        JsonObject manifest = JsonParser.parseString(Files.readString(Paths.get(args[0]))).getAsJsonObject();
        JsonArray specs = manifest.getAsJsonArray("functions");
        if (specs.size() < 1 || specs.size() > 32) throw new IOException("function count bound");
        Map<String,Object> report = new LinkedHashMap<>();
        report.put("schemaVersion", 1);
        report.put("profile", args[2]);
        report.put("ghidraVersion", Application.getApplicationVersion());
        report.put("javaVersion", System.getProperty("java.version"));
        report.put("jvmMaxHeapBytes", Runtime.getRuntime().maxMemory());
        report.put("availableProcessors", Runtime.getRuntime().availableProcessors());
        report.put("binarySha256", currentProgram.getExecutableSHA256());
        report.put("analysisTimedOut", analysisTimeoutOccurred());
        if (Runtime.getRuntime().maxMemory() > 1073741824L ||
            Runtime.getRuntime().availableProcessors() > 2) throw new IOException("analysis/resource profile failed");
        if (!currentProgram.getExecutableSHA256().equalsIgnoreCase(manifest.get("binarySha256").getAsString()))
            throw new IOException("binary hash mismatch");
        if (analysisTimeoutOccurred()) {
            List<Map<String,Object>> timedOut = new ArrayList<>();
            for (JsonElement spec : specs) {
                Map<String,Object> failure = new LinkedHashMap<>();
                failure.put("id", spec.getAsJsonObject().get("id").getAsString());
                failure.put("status", "timeout");
                failure.put("stage", "ghidra_auto_analysis");
                failure.put("reason", "Ghidra auto-analysis exceeded 120-second deadline");
                timedOut.add(failure);
            }
            report.put("functions", timedOut);
            report.put("status", "timeout");
            writeReport(Paths.get(args[1]), report);
            return;
        }
        DecompInterface decompiler = new DecompInterface();
        List<Map<String,Object>> functions = new ArrayList<>();
        try {
            if (!decompiler.setSimplificationStyle("decompile") || !decompiler.toggleSyntaxTree(true) ||
                !decompiler.toggleCCode(true) || !decompiler.openProgram(currentProgram))
                throw new IOException("decompiler configuration failed");
            for (JsonElement spec : specs) {
                try { functions.add(extract(spec.getAsJsonObject(), decompiler)); }
                catch (Exception error) {
                    Map<String,Object> failure = new LinkedHashMap<>();
                    failure.put("id", spec.getAsJsonObject().get("id").getAsString());
                    failure.put("status", "error"); failure.put("reason", error.toString());
                    functions.add(failure);
                }
            }
        } finally { decompiler.dispose(); }
        report.put("functions", functions);
        report.put("status", "completed");
        writeReport(Paths.get(args[1]), report);
    }
}
