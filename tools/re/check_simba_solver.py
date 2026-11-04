"""Explicit solver checks for the optional, pinned RE evaluation environment."""
import unittest
import z3
import simba


class SolverContractTests(unittest.TestCase):
    def test_z3_uses_declared_modular_width(self):
        self.assertEqual(z3.get_version_string(), simba.Z3_VERSION)
        self.assertEqual(simba.prove("p0+4294967296", "p0", 32, z3), "unsat")
        self.assertEqual(simba.prove("p0+4294967296", "p0", 64, z3), "sat")
        self.assertEqual(simba.prove("(p0^p1)+2*(p0&p1)", "p0+p1", 64, z3), "unsat")


if __name__ == "__main__":
    unittest.main()
