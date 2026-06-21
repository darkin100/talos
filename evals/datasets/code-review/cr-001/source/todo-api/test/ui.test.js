const puppeteer = require('puppeteer');

describe('Todo App Inline Edit', () => {
  let browser;
  let page;

  beforeAll(async () => {
    browser = await puppeteer.launch();
    page = await browser.newPage();
    await page.goto('http://localhost:3000');
  });

  afterAll(async () => {
    await browser.close();
  });

  test('should toggle to edit mode and back', async () => {
    await page.waitForSelector('#title-1');

    const initialText = await page.$eval('#title-1', el => el.textContent);
    await page.click('button[onclick="toggleEditMode(1)"]');

    const inputVisible = await page.$eval('#input-1', el => !el.classList.contains('hidden'));
    expect(inputVisible).toBe(true);

    await page.type('#input-1', ' Updated');
    await page.keyboard.press('Enter');

    const updatedText = await page.$eval('#title-1', el => el.textContent);
    expect(updatedText).toBe(initialText + ' Updated');
  });

  test('should cancel edit on Escape', async () => {
    await page.waitForSelector('#title-1');

    await page.click('button[onclick="toggleEditMode(1)"]');
    await page.type('#input-1', ' Cancelled');
    await page.keyboard.press('Escape');

    const isInputHidden = await page.$eval('#input-1', el => el.classList.contains('hidden'));
    const titleVisibleText = await page.$eval('#title-1', el => el.textContent);

    expect(isInputHidden).toBe(true);
    expect(titleVisibleText).not.toContain('Cancelled');
  });
});