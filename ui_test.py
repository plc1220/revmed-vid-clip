import pytest
from playwright.sync_api import Page, expect

def test_e2e_video_processing_workflow(page: Page):
    """
    Tests the full end-to-end video processing workflow from the Streamlit UI.
    """
    # 1. Navigate to the app
    page.goto("http://127.0.0.1:8501")

    # --- Tab 1: Video Split ---
    
    # Navigate to the "Video Split" tab (it's the default tab)
    # No action needed as it's the first tab

    # Upload a video file
    page.set_input_files("input[type='file']", "test.mp4")

    # Click the button to start splitting
    page.click("text=🚀 Upload to GCS and Start Splitting")

    # Wait for the job to complete
    expect(page.locator("text=✅ **Job Complete:**")).to_be_visible(timeout=120000) # 2 minute timeout

    # --- Tab 2: Metadata Generation ---
    page.click("text=2: Metadata Generation")

    # The videos should be found automatically. Click the generate button.
    page.click("text=✨ Generate Metadata via API")

    # Wait for the job to complete
    expect(page.locator("text=✅ **Job Complete:**")).to_be_visible(timeout=180000) # 3 minute timeout

    # --- Tab 3: Clip Generation ---
    page.click("text=3: Clip Generation")

    # Select the first available metadata file
    page.locator("div[data-baseweb='select']").click()
    page.locator("li[role='option']").nth(1).click() # nth(0) is the placeholder

    # Click the generate button
    page.click("text=✨ Generate Clips via API")

    # Wait for the job to complete
    expect(page.locator("text=✅ **Job Complete:**")).to_be_visible(timeout=180000) # 3 minute timeout

    # --- Tab 4: Video Joining ---
    page.click("text=4: Video Joining")

    # Select all available clips
    page.locator("input[type='checkbox']").all_inner_texts()
    for i in range(page.locator("input[type='checkbox']").count()):
        page.locator("input[type='checkbox']").nth(i).check()

    # Click the stitch button
    page.click("text=🎬 Stitch Selected Clips via API")

    # Wait for the job to complete
    expect(page.locator("text=✅ **Job Complete:**")).to_be_visible(timeout=180000) # 3 minute timeout
