import { execSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));

/** Generates a small text-based PDF via the backend venv's PyMuPDF.
 *  Returns the absolute path to the created file. */
export function makePdf(text: string, filename = "e2e-notes.pdf"): string {
  const dir = join(tmpdir(), "pdf-qa-e2e");
  mkdirSync(dir, { recursive: true });
  const path = join(dir, filename);
  const python = join(HERE, "..", "..", "backend", ".venv", "Scripts", "python.exe");
  const script = join(HERE, "gen_pdf.py");
  execSync(`"${python}" "${script}" "${path}" "${text.replace(/"/g, "'")}"`, {
    stdio: "ignore",
  });
  return path;
}
