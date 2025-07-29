# Cookie Retrieval Guide for Rezka Downloader

This guide explains how to obtain `dle_user_id` and `dle_password` cookies required for downloading from `standby-rezka.tv` or custom URLs with the Rezka Downloader script. It’s designed for beginners with no prior experience using browser developer tools.

## Prerequisites

- A web browser (e.g., Google Chrome, Firefox, Edge).
- An account on the target site (e.g., `standby-rezka.tv`).

## Step-by-Step Instructions

1. **Open the Website**:
   - Navigate to the site requiring login (e.g., [standby-rezka.tv](https://standby-rezka.tv)).
   - Log in with your account credentials.

2. **Open Developer Tools**:
   - On Windows/Linux: Press `Ctrl + Shift + I` or `F12`.
   - On Mac: Press `Cmd + Option + I`.
   - This opens the browser’s Developer Tools panel.

3. **Go to the Network Tab**:
   - In Developer Tools, click the **Network** tab (you may need to refresh the page with `F5` to see requests).
   - Perform an action on the site (e.g., search for a movie or click a link) to generate network requests.

4. **Find a Request**:
   - In the **Network** tab, you’ll see a list of requests (e.g., `index.php`, `search`, etc.).
   - Click any request to view its details.

5. **Locate Cookies**:
   - In the request details, find the **Cookies** section (may be under **Headers**).
   - Look for:
     - `dle_user_id`: A numeric value (e.g., `123456`).
     - `dle_password`: A hash-like value (e.g., `abc123def456`).
   - Copy these values exactly as they appear.

6. **Use in Rezka Downloader**:
   - When prompted by the script for `dle_user_id` and `dle_password`, paste the copied values.
   - Example input:
     ```
     Enter dle_user_id: 123456
     Enter dle_password: abc123def456
     ```

## Notes

- **Cookie Expiration**: Cookies may expire (e.g., after logging out or session timeout). Repeat these steps to get new cookies if login fails.
- **Privacy**: Do not share your cookies publicly, as they grant access to your account.
- **Troubleshooting**: If cookies don’t work, ensure you’re logged in and try a different request in the **Network** tab.