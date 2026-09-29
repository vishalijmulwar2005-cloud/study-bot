import { expect, test } from "@playwright/test";
import { makePdf } from "../helpers/makePdf";

/** Responsive + recovery checks (Phase 26 test 10; UX-07/08). */

test("mobile: sidebar becomes drawer, document scope stays visible", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByText("Upload a PDF to get started")).toBeVisible();

  await page.setInputFiles(
    "#pdf-upload-input",
    makePdf("Mobile layout verification document about paging.", "mobile.pdf"),
  );
  const card = page.getByRole("region", { name: "Active document" });
  await expect(card).toBeVisible({ timeout: 120_000 });

  // Top bar keeps the active filename visible without the sidebar.
  await expect(page.locator("header").getByText("mobile.pdf")).toBeVisible();

  // Drawer opens via the menu button.
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("complementary")).toBeVisible();
});

test("failed processing shows a recoverable error card with retry", async ({ page }) => {
  await page.goto("/");
  // Corrupt PDF: right magic bytes, garbage body -> backend FAILED state.
  const corrupt = Buffer.from("%PDF-1.7 definitely not a real pdf body");
  await page.setInputFiles("#pdf-upload-input", {
    name: "corrupt.pdf",
    mimeType: "application/pdf",
    buffer: corrupt,
  });
  const card = page.getByRole("region", { name: "Active document" });
  await expect(card.getByText("Failed")).toBeVisible({ timeout: 60_000 });
  await expect(card.getByRole("button", { name: "Retry processing" })).toBeVisible();
});
