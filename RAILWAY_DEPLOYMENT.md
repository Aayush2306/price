# 🚀 Railway Deployment Guide for PredictGram Backend

## Prerequisites
- GitHub account
- Railway account (sign up at https://railway.app)
- Your API keys ready (CoinGecko, Twelve Data, Dune Analytics)

---

## Step 1: Push Your Code to GitHub

```bash
cd backend
git add .
git commit -m "Prepare backend for Railway deployment"
git push origin main
```

---

## Step 2: Create New Railway Project

1. Go to https://railway.app
2. Click **"New Project"**
3. Select **"Deploy from GitHub repo"**
4. Select your **PredictGram** repository
5. Select the **backend** folder as root directory

---

## Step 3: Add PostgreSQL Database

1. In your Railway project, click **"+ New"**
2. Select **"Database"**
3. Choose **"Add PostgreSQL"**
4. Railway will automatically:
   - Create a PostgreSQL instance
   - Set the `DATABASE_URL` environment variable
   - Connect it to your app

---

## Step 4: Configure Environment Variables

In Railway dashboard, go to your backend service → **Variables** tab:

### Required Variables:

```bash
# Security (IMPORTANT - Change these!)
SECRET_KEY=your-random-secret-key-min-32-characters-long

# Session Cookies
SESSION_COOKIE_SAMESITE=None
SESSION_COOKIE_SECURE=1

# CORS - Your Frontend URL
ALLOWED_ORIGINS=https://your-frontend-app.vercel.app

# API Keys
CG_API_KEY=your-coingecko-api-key
TWELVE_API_KEY=your-twelve-data-api-key
DUNE_API_KEY=your-dune-analytics-api-key

# Optional
FLASK_DEBUG=0
REDIS_DISABLE=1
```

### 🔐 How to Generate SECRET_KEY:
```python
import secrets
print(secrets.token_hex(32))
# Copy the output and use it as SECRET_KEY
```

---

## Step 5: Deploy!

1. Railway will automatically detect your `Procfile` and `requirements.txt`
2. Click **"Deploy"**
3. Wait 3-5 minutes for build and deployment
4. You'll get a public URL like: `https://your-app.up.railway.app`

---

## Step 6: Verify Deployment

### Check Logs:
1. Go to your Railway project
2. Click on your backend service
3. Click **"Deployments"** → **"View Logs"**
4. Look for:
   ```
   ✅ Database tables created successfully
   ✅ Server started on port XXXX
   ```

### Test Endpoints:
```bash
# Health check
curl https://your-app.up.railway.app/api/market-status

# Should return market status JSON
```

---

## Step 7: Update Frontend CORS

Once deployed, update your frontend to use the Railway backend URL:

**Frontend `.env` or config:**
```bash
VITE_API_URL=https://your-app.up.railway.app
```

---

## 📊 Monitoring & Maintenance

### View Logs:
- Railway Dashboard → Your Service → **View Logs**

### Database Access:
1. Railway Dashboard → PostgreSQL Service
2. Click **"Data"** tab to view/query database
3. Or use **"Connect"** to get connection string for external tools

### Restart Service:
- Railway Dashboard → Your Service → Settings → **Restart**

---

## 💰 Cost Estimate

**Hobby Plan ($5/month):**
- Backend: ~$3/month
- PostgreSQL: ~$2/month
- **Total: ~$5/month**

Railway shows real-time usage in dashboard.

---

## 🔧 Troubleshooting

### ❌ Build Fails
**Check:**
1. All dependencies in `requirements.txt`
2. Python version compatibility
3. Build logs for specific errors

### ❌ App Crashes on Start
**Check:**
1. Environment variables are set correctly
2. `DATABASE_URL` is automatically provided by Railway
3. Logs for error messages

### ❌ Database Connection Error
**Make sure:**
1. PostgreSQL service is running
2. `DATABASE_URL` variable exists (Railway auto-sets this)
3. Database and app are in same Railway project

### ❌ CORS Errors
**Fix:**
1. Set `ALLOWED_ORIGINS` to your frontend URL
2. Must be exact match (no trailing slash)
3. Multiple origins: `https://app1.com,https://app2.com`

### ❌ Background Workers Not Running
**Check:**
1. Using `eventlet` worker in Procfile (✅ already configured)
2. Check logs for thread startup messages
3. Threads should start automatically

---

## 🎯 Post-Deployment Checklist

- [ ] Backend is deployed and running
- [ ] PostgreSQL database is connected
- [ ] All environment variables are set
- [ ] API endpoints are accessible
- [ ] Frontend can connect to backend
- [ ] CORS is configured correctly
- [ ] Background workers are running (check logs)
- [ ] Test placing a bet and resolving rounds

---

## 🔄 Updating Your App

Railway auto-deploys when you push to GitHub:

```bash
# Make changes to your code
git add .
git commit -m "Update backend"
git push origin main

# Railway automatically:
# 1. Detects the push
# 2. Rebuilds your app
# 3. Deploys the new version
# 4. Zero-downtime deployment
```

---

## 📱 Next Steps

1. **Deploy Frontend** (Vercel/Netlify recommended)
2. **Configure Custom Domain** (optional, in Railway settings)
3. **Set up monitoring** (Railway has built-in metrics)
4. **Enable auto-scaling** if needed (Pro plan)

---

## 🆘 Need Help?

- Railway Docs: https://docs.railway.app
- Railway Discord: https://discord.gg/railway
- Check deployment logs first (90% of issues show there)

---

**Your backend is production-ready! 🎉**
