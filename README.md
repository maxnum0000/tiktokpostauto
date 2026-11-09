# tiktokpostauto

A small, **compliant** command-line tool that publishes videos you own to your
own TikTok account using TikTok's **official Content Posting API**.

It is the sanctioned alternative to browser automation: the account owner
authorizes the app via OAuth, and posting goes through TikTok's documented API.

## What this is NOT
- It does **not** automate the TikTok app/website with a headless browser.
- It does **not** create accounts or inflate followers/likes/comments.
- It only posts your own content to your own authorized account.

## Setup
1. Create an app at <https://developers.tiktok.com>, add the **Login Kit** and
   **Content Posting API** products, and request the `video.upload` /
   `video.publish` scopes.
2. Copy `.env.example` to `.env` and fill in your `TIKTOK_CLIENT_KEY`,
   `TIKTOK_CLIENT_SECRET`, and `TIKTOK_REDIRECT_URI`.
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage
```bash
# 1) Get the OAuth consent URL (reads config from .env), open it, authorize,
#    and copy the ?code=... from the redirect.
python post_to_tiktok.py auth-url

# 2) Exchange the code for tokens; paste access_token into .env.
python post_to_tiktok.py token --code <CODE>

# 3) Publish a video you own (private by default).
python post_to_tiktok.py post --file video.mp4 --title "caption"
```

## Important limits
- Access tokens expire ~24h (refresh with your refresh token).
- Until your app passes TikTok's audit, posts are restricted to private
  (`SELF_ONLY`) and a small number of test users.
- Respect TikTok's per-account publishing rate limits and Community Guidelines.

## Legal pages
`legal/` contains Terms of Service and Privacy Policy templates you can host
(e.g. GitHub Pages or Netlify) to supply the URLs TikTok's app review requires.
Replace the bracketed placeholders before publishing.
