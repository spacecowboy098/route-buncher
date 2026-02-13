# Deployment Guide: The Buncher on Streamlit Cloud

This guide will walk you through deploying The Buncher route optimizer to Streamlit Community Cloud (free hosting).

## Prerequisites

- GitHub account (you already have this: https://github.com/runerra/route-buncher)
- Google Maps API key (you have this)
- Anthropic API key (optional, for AI features)

## Step-by-Step Deployment

### 1. Sign Up for Streamlit Community Cloud

1. Go to **https://share.streamlit.io/**
2. Click **"Sign in"**
3. Choose **"Continue with GitHub"**
4. Authorize Streamlit to access your GitHub account

### 2. Deploy Your App

1. In the Streamlit Cloud dashboard, click **"New app"**
2. Fill in the deployment form:
   - **Repository**: `runerra/route-buncher`
   - **Branch**: `main`
   - **Main file path**: `app.py`
3. Click **"Deploy!"**

The app will start building. This takes 2-5 minutes the first time.

### 3. Configure Secrets (REQUIRED!)

Your app needs API keys to function. Configure them as secrets:

1. In your Streamlit Cloud dashboard, find your deployed app
2. Click the **"⚙️ Settings"** button (bottom right)
3. Select **"Secrets"** from the left menu
4. Paste the following into the secrets editor:

```toml
GOOGLE_MAPS_API_KEY = "your-google-maps-api-key-here"
ANTHROPIC_API_KEY = "your-anthropic-api-key-here"
DEPOT_ADDRESS = "3710 Dix Hwy Lincoln Park, MI 48146"
DEFAULT_VEHICLE_CAPACITY = "300"
SERVICE_TIME_METHOD = "smart"
FIXED_SERVICE_TIME = "3"
APP_PASSWORD = "spaceCowboy"
```

**IMPORTANT**: Replace the placeholder values with your actual API keys:
- Get your Google Maps API key from your `.env` file
- Get your Anthropic API key from your `.env` file
- Keep the DEPOT_ADDRESS, DEFAULT_VEHICLE_CAPACITY, and APP_PASSWORD as shown
- Change APP_PASSWORD if you want a different password
- SERVICE_TIME_METHOD: "smart" (variable by units) or "fixed" (same time per stop)
- FIXED_SERVICE_TIME: Minutes per stop (only used if method is "fixed")

5. Click **"Save"**
6. The app will automatically restart with the secrets loaded

### 4. Access Your Live App

Once deployment is complete, you'll get a public URL:

```
https://route-buncher.streamlit.app
```

or something like:

```
https://runerra-route-buncher-xxxxx.streamlit.app
```

Share this URL with anyone who needs to use the route optimizer!

**🔒 Password Protection**: When users visit the app, they'll be prompted to enter a password. The default password is **`spaceCowboy`** (set in the APP_PASSWORD secret). Share this password only with authorized users.

## What Gets Deployed

When you deploy, Streamlit Cloud will:

- ✅ Clone your GitHub repository
- ✅ Install all dependencies from `requirements.txt`
- ✅ Run `app.py` on their servers
- ✅ Provide a public HTTPS URL
- ✅ Auto-redeploy when you push to GitHub

## Features Available in Cloud

All features work in the cloud deployment:

- ✅ Password protection (login required)
- ✅ CSV upload and parsing
- ✅ Google Maps geocoding and routing
- ✅ Route optimization (3 cuts)
- ✅ Interactive maps (Folium)
- ✅ AI chat assistant (Claude)
- ✅ Dispatcher sandbox
- ✅ KPI metrics and visualizations

## Password Protection

The app requires a password to access. This prevents unauthorized users from accessing your route optimization tool.

### How It Works

1. When users visit the app URL, they see a login screen
2. They must enter the correct password (default: `spaceCowboy`)
3. Once authenticated, they can use all features
4. The session persists until they close the browser or clear cookies

### Changing the Password

To change the password:

1. Go to Streamlit Cloud dashboard → Settings → Secrets
2. Change the `APP_PASSWORD` value to your new password
3. Click "Save"
4. The app will restart with the new password

Example:
```toml
APP_PASSWORD = "myNewSecurePassword123"
```

### Security Notes

- Password is stored in Streamlit Secrets (encrypted at rest)
- Password is never committed to GitHub
- Password is transmitted over HTTPS only
- Sessions are browser-specific (each user must login)
- No password recovery - if forgotten, update in Streamlit Secrets

### Sharing Access

To share the app with your team:

1. Share the app URL: `https://route-buncher.streamlit.app`
2. Share the password: `spaceCowboy` (or your custom password)
3. Instruct them to enter the password when prompted

**Important**: This is basic password protection. For production use with sensitive data, consider:
- Using Streamlit's built-in authentication (requires paid plan)
- Deploying to a private network
- Implementing OAuth/SSO integration

## Updating Your Deployed App

Any time you push changes to GitHub, Streamlit Cloud will automatically redeploy:

```bash
git add .
git commit -m "Update feature X"
git push
```

Wait 1-2 minutes and your live app will update!

## Monitoring & Settings

### View Logs

1. In Streamlit Cloud dashboard, click your app
2. Click **"⋮"** (three dots) → **"Logs"**
3. See real-time logs, errors, and user activity

### App Settings

Click **"⚙️ Settings"** to configure:

- **Secrets**: Update API keys
- **Resources**: Check CPU/memory usage
- **Sharing**: Make app private or public
- **Custom domain**: Add your own domain (e.g., optimizer.yourdomain.com)

## Troubleshooting

### App Won't Start

**Symptom**: Deployment fails or app shows error

**Solution**: Check logs for errors. Common issues:
- Missing secrets (add them in Settings → Secrets)
- Wrong Python version (Streamlit Cloud uses Python 3.11)
- Missing dependency in requirements.txt

### "Module Not Found" Error

**Symptom**: `ModuleNotFoundError: No module named 'xyz'`

**Solution**: Add the missing package to `requirements.txt`:

```bash
echo "package-name>=1.0.0" >> requirements.txt
git add requirements.txt
git commit -m "Add missing dependency"
git push
```

### Maps Not Loading

**Symptom**: Map shows blank or error

**Solution**: Check Google Maps API key in Secrets:
1. Go to Settings → Secrets
2. Verify `GOOGLE_MAPS_API_KEY` is correct
3. Check that Google Maps API is enabled in Google Cloud Console
4. Verify billing is enabled (required for Maps API)

### AI Chat Not Working

**Symptom**: Chat shows "not configured" or errors

**Solution**: Check Anthropic API key in Secrets:
1. Go to Settings → Secrets
2. Verify `ANTHROPIC_API_KEY` is correct
3. Check that API key is active at https://console.anthropic.com/

## Costs

### Streamlit Community Cloud

- **Free**: Unlimited public apps
- **Free**: 1GB resources per app
- **Free**: Community support

For private apps or more resources, consider Streamlit Pro ($20/month).

### API Usage

Your deployed app will use:

- **Google Maps API**: ~$0.005 per geocode, $0.005 per distance matrix call
  - Estimate: $0.20-0.50 per optimization (20-40 addresses)
- **Anthropic API**: ~$0.02-0.05 per optimization with AI
  - Free tier: $5 credit (100-250 optimizations)

### Monthly Cost Estimate

For 100 optimizations/month:
- Google Maps API: ~$20-50
- Anthropic API: ~$2-5 (if using AI)
- Streamlit Cloud: $0 (free tier)

**Total: $22-55/month**

## Security Best Practices

### API Keys

- ✅ Never commit `.env` to GitHub (already in `.gitignore`)
- ✅ Use Streamlit Secrets for production keys
- ✅ Rotate API keys every 3-6 months
- ✅ Set spending limits in Google Cloud Console and Anthropic Console

### Access Control

By default, your app is public. To restrict access:

1. Go to Settings → Sharing
2. Options:
   - **Public**: Anyone with URL can access
   - **Private**: Only you can access
   - **Invite-only**: Share with specific email addresses

### Data Privacy

Uploaded CSV files:
- ✅ Stored in memory only (never written to disk)
- ✅ Deleted when session ends
- ✅ Not accessible to other users

API data:
- Google Maps: Addresses sent to Google for geocoding
- Anthropic: Order data sent to Claude for AI explanations
- See `CLAUDE.md` for full AI privacy details

## Custom Domain (Optional)

Want a custom URL like `optimizer.buncha.com` instead of `route-buncher.streamlit.app`?

1. In Streamlit Cloud, go to Settings → General
2. Click **"Custom domain"**
3. Follow instructions to add CNAME record to your DNS
4. SSL certificate is automatically provisioned

## Support

- **Streamlit Docs**: https://docs.streamlit.io/
- **Community Forum**: https://discuss.streamlit.io/
- **GitHub Issues**: Report bugs at https://github.com/runerra/route-buncher/issues

## Next Steps

1. ✅ Deploy app to Streamlit Cloud (follow steps above)
2. ✅ Add secrets (API keys)
3. ✅ Test the live app with sample CSV
4. ✅ Share URL with team
5. ✅ Monitor usage and costs

---

**Your Live App URL**: https://route-buncher.streamlit.app (or custom URL from dashboard)

**Repository**: https://github.com/runerra/route-buncher

**Deployed with Streamlit Community Cloud**
