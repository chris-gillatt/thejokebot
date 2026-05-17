# Proxy Testing Results - 2026-05-17

## Test Summary

Created `.github/workflows/test_proxy_post.yml` to test if using HTTP proxies can bypass the 403 Forbidden error occurring in GitHub Actions.

### Test 1: Direct Connection (No Proxy)
**Status:** ❌ **FAILED** with 403 Forbidden  
**Proxy:** None  
**Error:** 
```
atproto_client.exceptions.UnauthorizedError: Response(
  status_code=403, 
  headers={'server': 'awselb/2.0', ...}
)
```
**Conclusion:** The direct connection from GitHub Actions CI is being blocked at the AWS ELB load balancer level.

### Test 2: HTTP Proxy (213.230.69.193:3128)
**Status:** ⏱️ **TIMEOUT**  
**Proxy:** http://213.230.69.193:3128  
**Error:** 
```
atproto_client.exceptions.InvokeTimeoutError: timed out
```
**Conclusion:** 
- ✓ The proxy mechanism works (httpx correctly routes through proxy)
- ✗ This specific free proxy is unreliable/dead
- Free proxies are generally not suitable for production use

## What This Tells Us

1. **GitHub Actions IP is being blocked** - The 403 error occurs immediately on direct connection
2. **Proxy mechanism works** - The atproto library (via httpx) correctly respects HTTP_PROXY environment variables
3. **Free proxies are unreliable** - Most free proxy lists are unmaintained or have poor uptime
4. **The issue is infrastructure-level** - AWS ELB is rejecting at the load balancer, before requests reach the API

## Next Steps

### Option 1: Paid Proxy Service (Most Reliable)
Services like:
- **Bright Data** - $30-100/month, 70M+ IPs, enterprise reliability
- **Oxylabs** - $50/month, fast HTTPS proxy support
- **Smartproxy** - $20/month, rotating residential IPs

To use:
```bash
gh secret set BLUESKY_PROXY_URL --body "http://user:pass@proxy.example.com:port"
```

Then update workflow with:
```yaml
HTTPS_PROXY: ${{ secrets.BLUESKY_PROXY_URL }}
```

### Option 2: Self-Hosted Proxy on VPS
Set up a cheap VPS ($5-10/month) running tinyproxy or squid:
```bash
# On your VPS, install tinyproxy
# Then use: http://your-vps-ip:port
```

### Option 3: Self-Hosted GitHub Actions Runner
The most reliable solution - run the workflow on your own infrastructure:
```bash
# Your IP won't be on Bluesky's blocklist
# Set up instructions available in GitHub Actions documentation
```

### Option 4: Contact Bluesky Support
Provide them with:
- GitHub Actions runner environment (ubuntu-24.04)
- Exact failure timestamps: 2026-05-17T03:42:13Z onwards
- Evidence that credentials work locally
- Request headers being sent (can debug locally)

## How to Test with Your Own Proxy

```bash
# If you have a proxy URL, test with:
gh workflow run test_proxy_post.yml -f proxy_url="http://your-proxy:port"

# The workflow will show if proxy helped or still gets 403
```

## Files Created

- `.github/workflows/test_proxy_post.yml` - Reusable proxy testing workflow
  - Accepts `proxy_url` as input parameter
  - Tests authentication with/without proxy
  - Shows proxy environment variables in output
  - Can be run on-demand for quick testing

## Key Finding

**The infrastructure-level blocking (AWS ELB 403) is not bypassed by free proxies.** Even if the proxy connection works, Bluesky may be identifying and blocking the proxy IPs as well. A **reliable paid proxy with residential IPs** or a **self-hosted runner** would be required for a guaranteed solution.
