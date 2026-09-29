import { expect, test } from "@playwright/test";
import { makePdf } from "../helpers/makePdf";

/** Core happy path (Phase 26 tests 1–2) and no-evidence path (test 3).
 *  Requires: backend on :8000 with a real DB + configured providers,
 *  frontend dev server on :5173. */

const DOC_TEXT =
  "E2E test document. The banker's algorithm avoids deadlock by keeping the " +
  "system in a safe state before granting resource requests.";

test("upload -> ready -> grounded answer with page source", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Upload a PDF to get started")).toBeVisible();

  await page.setInputFiles("#pdf-upload-input", makePdf(DOC_TEXT, "happy.pdf"));
  const card = page.getByRole("region", { name: "Active document" });
  await expect(card).toBeVisible();
  await expect(card.getByText("Ready")).toBeVisible({ timeout: 120_000 });

  await page.getByLabel("Ask a question about the active PDF").fill(
    "How does the banker's algorithm avoid deadlock?",
  );
  await page.getByRole("button", { name: "Send question" }).click();

  const answer = page.locator(".answer-markdown").first();
  await expect(answer).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Page \d+/).first()).toBeVisible();
});

test("unrelated question gets the no-evidence response", async ({ page }) => {
  await page.goto("/");
  await page.setInputFiles("#pdf-upload-input", makePdf(DOC_TEXT, "unrelated.pdf"));
  const card = page.getByRole("region", { name: "Active document" });
  await expect(card.getByText("Ready")).toBeVisible({ timeout: 120_000 });

  await page
    .getByLabel("Ask a question about the active PDF")
    .fill("What is the capital of France?");
  await page.getByRole("button", { name: "Send question" }).click();

  await expect(
    page.getByText("I couldn't find this information in the uploaded PDF."),
  ).toBeVisible({ timeout: 60_000 });
});
