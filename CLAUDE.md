# Claude AI Integration Guide

Complete guide to the AI-powered features in The Buncher route optimizer.

---

## Overview

The Buncher integrates Claude AI (Anthropic) to provide intelligent explanations, validation, and interactive assistance for route optimization decisions. The AI features are **optional** - the optimizer works perfectly without them, but AI adds valuable insights for dispatchers.

---

## AI Features

### 1. **Route Validation & Explanation**

When you run optimization with AI enabled, Claude analyzes the results and provides:

- **Math Validation**: Confirms capacity and time constraints are respected
- **Logic Verification**: Explains why specific orders were kept or dropped
- **Strategic Insights**: Why this particular route is optimal
- **Risk Assessment**: Flags tight margins or edge cases to watch

**Example Output:**
```
✅ Route validation confirms all constraints met. The optimizer kept 14 orders
(78 units, 98% capacity) within the 120-minute window. Orders were dropped
due to geographic isolation - the 3 cancelled orders average 22+ minutes from
the cluster, making them cost-prohibitive to serve. The route operates at
92% time utilization, leaving minimal buffer but maximizing delivery efficiency.
```

### 2. **Interactive Chat Assistant**

After optimization, you can ask Claude questions about the route:

**Common Questions:**
- "Why is order #70592 not included?"
- "Can you add back order #70610?"
- "What would happen if I remove order #70509?"
- "Which rescheduled orders are closest to the route?"
- "How can I fit more orders in this route?"

**What the AI Knows:**
- Every order's address, units, and delivery window
- Exact distances between all stops
- Current capacity and time utilization
- Why each order received its disposition (KEEP/EARLY/RESCHEDULE/CANCEL)
- Geographic clusters and route efficiency metrics

**What the AI Can Do:**
- Explain specific optimization decisions with data
- Estimate feasibility of adding orders back (capacity + geography)
- Calculate impact of removing orders from the route
- Suggest which dropped orders are easiest to add
- Answer "what if" scenarios

**What the AI Cannot Do:**
- Modify the route (you must re-run optimization or use Cut 4: Dispatcher Sandbox)
- Override physical constraints (capacity, time windows)
- Access real-time traffic data

---

## How to Use AI Features

### Setup (One-Time)

1. **Get Anthropic API Key**:
   - Go to [console.anthropic.com](https://console.anthropic.com/)
   - Sign up or log in
   - Navigate to **API Keys** → **Create Key**
   - Copy your API key

2. **Add to .env File**:
   ```env
   ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxx
   ```

3. **Restart the App**:
   ```bash
   streamlit run app.py
   ```

### Running Optimization

You have two buttons:

**🚀 Run (with AI)** - Full AI features:
- Route validation and explanation
- AI-generated order disposition reasons
- Interactive chat assistant enabled
- Takes ~5-10 seconds longer
- Costs ~$0.01-0.05 per optimization

**⚡ Run (no AI)** - Fast optimization:
- Same routing logic and results
- Generic disposition reasons
- No chat assistant
- Completes in ~2-5 seconds
- Free (only uses Google Maps API)

**Recommendation**: Use "Run (no AI)" during testing/debugging, then "Run (with AI)" for final routes you'll share with drivers.

---

## AI Chat Usage

### Starting a Conversation

After running optimization with AI:

1. Navigate to any Cut tab (Cut 1, 2, 3, or 4)
2. Scroll to the **"💬 Chat Assistant"** section
3. Type your question in the text input
4. Click **Send** or press Enter

### Best Practices

**Be Specific with Order Numbers:**
- ✅ "Why was order #70592 dropped?"
- ❌ "Why were some orders dropped?"

**Ask One Question at a Time:**
- ✅ "Can you add back order #70610?"
- ❌ "Can you add back orders #70610, #70611, and #70612 and also remove order #70509?"

**Reference Actual Data:**
- The AI has the exact optimization context
- It knows distances, capacities, and constraints
- You don't need to re-explain the route

**Follow Up Naturally:**
- "What about order #70611?"
- "How much capacity would that free up?"
- "Which orders are closest to the cluster?"

### Example Conversation

```
Dispatcher: Why was order #70610 not included?

Claude: Order #70610 (15 units, Plymouth delivery) was recommended for
rescheduling because it's located 14.2 minutes from the main route cluster.
Adding it would increase route time by ~28 minutes (drive there + back to route),
which exceeds your remaining time buffer of 9 minutes. The current route uses
111/120 minutes (92.5%) of your delivery window.

Dispatcher: Can you add it back if I remove order #70509?

Claude: Yes, that swap would work. Removing order #70509 would free up:
- 12 units of capacity (currently at 78/80 units, so margin is tight)
- ~18 minutes of route time (it's stop #3, mid-route)

Adding order #70610 (15 units) would exceed capacity by 3 units. You'd need
to remove at least 15 units total. Consider removing both #70509 (12 units)
and #70511 (8 units) to comfortably fit #70610.

Reminder: Use Cut 4: Dispatcher Sandbox to test this manually, or re-run
optimization after adjusting constraints.
```

---

## Understanding AI-Generated Explanations

### Order Disposition Reasons

When AI is enabled, each order gets a specific, context-aware reason:

**KEEP Orders:**
- "Optimal position in cluster, minimizes total drive time while fitting capacity constraints"
- "High efficiency stop (22 units) in dense area, only 4 minutes from previous stop"
- "Geographic anchor point - central to cluster, enables efficient sequencing"

**EARLY Delivery:**
- "Only 8 minutes from route cluster and customer approved early delivery"
- "Could deliver 45 minutes early - customer indicated flexibility in delivery window"

**RESCHEDULE:**
- "15 minutes from cluster, would add significant time but could fit in adjacent window"
- "Located on periphery of service area - better fit for tomorrow's northeast route"

**CANCEL:**
- "25+ minutes from route cluster, cost to serve exceeds delivery value"
- "Geographic outlier - would require 40+ minute detour for 5-unit delivery"

### Route Validation Insights

AI validation checks for:

**Constraint Compliance:**
- Capacity: "78/80 units (97.5%)" ✅
- Time: "111/120 minutes (92.5%)" ✅

**Efficiency Metrics:**
- "14 orders in 111 minutes = 7.6 deliveries/hour"
- "Load factor 97.5% indicates excellent capacity utilization"

**Strategic Assessment:**
- "Tight time margin (9 min buffer) - minor delays could impact last 2 stops"
- "Route prioritizes order count over travel efficiency, as expected for per-order revenue model"

**Risk Flags:**
- "⚠️ Order #70515 scheduled to arrive at 10:58 AM with window ending 11:00 AM - 2-minute buffer"
- "✅ All stops have adequate service time buffer (3-7 minutes per stop)"

---

## AI Model Information

**Current Model**: Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`)

**Why This Model:**
- **Fast**: Responds in 2-5 seconds
- **Cost-Effective**: ~$0.01-0.05 per full optimization
- **Accurate**: Excellent at logistics reasoning and math validation
- **Context**: Can handle full route details (100+ orders)

**Token Usage:**
- Route validation: ~500-800 tokens (~$0.01)
- Chat message: ~300-500 tokens (~$0.005)
- Order explanations: ~1000-2000 tokens (~$0.02)

**Monthly Cost Estimate:**
- 10 optimizations/day with AI = ~$3-5/month
- 50 optimizations/day with AI = ~$15-25/month
- Chat questions: negligible additional cost

---

## Troubleshooting

### "⚠️ Chat assistant is not configured"

**Problem**: ANTHROPIC_API_KEY not found in .env file

**Solution**:
1. Create API key at [console.anthropic.com](https://console.anthropic.com/)
2. Add to `.env`: `ANTHROPIC_API_KEY=sk-ant-api03-xxxxx`
3. Restart app: `streamlit run app.py`

### "❌ Error communicating with AI assistant"

**Possible Causes:**
1. **Invalid API Key**: Check key format starts with `sk-ant-`
2. **Rate Limit**: Wait 60 seconds and try again
3. **Network Issue**: Check internet connection
4. **API Quota**: Check usage at [console.anthropic.com](https://console.anthropic.com/)

**Solution**: Verify API key in .env file, check Anthropic console for quota/status

### AI Response Seems Wrong

**Issue**: AI provides inaccurate information about orders

**Cause**: This is rare but can happen if optimization data is corrupted

**Solution**:
1. Re-run the optimization
2. Verify order data in CSV is correct
3. Check that geocoding completed successfully
4. If persistent, use "⚡ Run (no AI)" to isolate routing logic

### Chat Not Showing Up

**Issue**: No chat section appears after optimization

**Cause**: AI was not enabled during optimization run

**Solution**: Click **"🚀 Run (with AI)"** button instead of "⚡ Run (no AI)"

---

## Privacy & Security

### What Data is Sent to Anthropic?

When you use AI features, the following data is sent:

**Route Optimization Context:**
- Order IDs (e.g., #70592)
- Customer names (if in CSV)
- Delivery addresses
- Unit counts
- Time windows
- Geographic distances
- Optimization results (which orders kept/dropped)

**NOT Sent:**
- API keys (stored locally only)
- Payment information
- Historical order data
- Driver information

### Data Retention

- **Anthropic Policy**: Data sent via API is not used to train models
- **Retention**: Anthropic retains API data for 30 days for abuse monitoring, then deletes
- **Compliance**: Anthropic is SOC 2 Type II certified, GDPR compliant

### Security Best Practices

1. **Protect API Keys**: Never commit .env to version control
2. **Rotate Keys**: Generate new API keys every 3-6 months
3. **Monitor Usage**: Check Anthropic console regularly for unexpected usage
4. **Sensitive Data**: If orders contain PII, consider using "⚡ Run (no AI)"

---

## API Usage Monitoring

### Check Your Usage

1. Go to [console.anthropic.com](https://console.anthropic.com/)
2. Navigate to **Usage** dashboard
3. View API calls, tokens used, and costs

### Setting Spending Limits

1. In Anthropic console, go to **Settings** → **Billing**
2. Set **Monthly Spending Limit** (e.g., $50)
3. Configure **Email Alerts** for 50%, 75%, 90% thresholds

### Expected Usage

**Per Optimization with AI:**
- Route validation: ~700 tokens
- Order explanations: ~1500 tokens
- Total: ~2200 tokens (~$0.02-0.04)

**Per Chat Message:**
- Average: ~400 tokens (~$0.005)

**Monthly Estimate:**
- 20 optimizations + 50 chat messages = ~$1-2/month
- 100 optimizations + 200 chat messages = ~$5-8/month

---

## Advanced: Customizing AI Behavior

### Modifying System Prompts

AI prompts are in `chat_assistant.py`:

**Route Validation Prompt** (line 221):
- Controls what AI checks and validates
- Adjust to emphasize specific metrics

**Chat Context Prompt** (line 32):
- Defines AI's role and capabilities
- Customize for your business rules

**Example Customization:**
```python
# In chat_assistant.py, line 32
context = f"""You are an AI assistant helping a Buncha dispatcher...

CUSTOM BUSINESS RULES:
- Priority customers (IDs starting with 'VIP') should always be kept if possible
- Orders >30 units are more profitable - weight these higher
- Friday routes can run 15 minutes longer due to lighter traffic
...
"""
```

### Changing AI Model

To use a different Claude model (e.g., Claude Opus for more complex reasoning):

**In `chat_assistant.py`, lines 174 and 281:**
```python
# Current (Sonnet 4.5 - fast, cost-effective):
model="claude-sonnet-4-5-20250929"

# Alternative (Opus 4.5 - more capable, slower, more expensive):
model="claude-opus-4-5-20251101"

# Alternative (Haiku 3.5 - fastest, cheapest, less capable):
model="claude-haiku-3-5-20241022"
```

**Model Comparison:**
- **Sonnet 4.5** (default): Best balance of speed, accuracy, and cost
- **Opus 4.5**: Use for complex multi-constraint scenarios or detailed analysis
- **Haiku 3.5**: Use if cost is primary concern and questions are simple

---

## Comparison: With AI vs Without AI

| Feature | 🚀 With AI | ⚡ Without AI |
|---------|-----------|--------------|
| **Routing Logic** | Identical | Identical |
| **Order Count** | Same | Same |
| **Route Sequence** | Same | Same |
| **Optimization Time** | 5-10 seconds | 2-5 seconds |
| **Route Validation** | ✅ Detailed analysis | ❌ None |
| **Order Reasons** | ✅ Specific, context-aware | ✅ Generic |
| **Chat Assistant** | ✅ Full interactive Q&A | ❌ Not available |
| **Cost** | ~$0.02-0.05 per run | Free (Google Maps only) |
| **Best For** | Final routes, training, auditing | Testing, debugging, high-volume |

---

## FAQs

**Q: Is AI required for the optimizer to work?**
A: No. The routing algorithm (OR-Tools) works independently. AI only adds explanations and chat.

**Q: Will AI make routing decisions?**
A: No. AI only explains decisions made by the OR-Tools algorithm. It cannot override constraints or modify routes.

**Q: Can I use AI in Cut 4: Dispatcher Sandbox?**
A: Yes. After loading a cut and making manual edits, you can ask AI about the impact: "What happens if I move order #70510 to KEEP?"

**Q: Does AI learn from my routes over time?**
A: No. Each optimization is independent. AI doesn't retain memory between sessions per Anthropic's API policy.

**Q: Can AI help with CSV formatting issues?**
A: Not currently. AI only analyzes optimization results, not input data validation.

**Q: What if Anthropic API is down?**
A: Use "⚡ Run (no AI)" button. Routing works normally, you just won't get AI explanations.

**Q: Can I use a different AI provider (OpenAI, etc.)?**
A: Code currently only supports Anthropic. Contact maintainer if you need OpenAI integration.

---

## Best Practices

### When to Use AI

**✅ Use AI When:**
- Creating final routes for drivers
- Training new dispatchers
- Auditing optimization decisions
- Investigating why orders were dropped
- Explaining routes to customers/management
- Exploring "what if" scenarios

**⚡ Skip AI When:**
- Testing different configurations rapidly
- Running multiple iterations for debugging
- Optimizing for high-volume operations (>100 routes/day)
- Working with sensitive customer data
- API quota is running low

### Getting Better AI Responses

1. **Be Specific**: Reference exact order IDs
2. **One Topic**: Ask focused questions, not compound queries
3. **Use Context**: AI knows the full route, no need to re-explain
4. **Check KPIs First**: Many questions answered by metrics (capacity %, route time)
5. **Iterate**: Ask follow-ups to drill deeper

### Cost Optimization

1. **Test Without AI First**: Use "⚡ Run (no AI)" for configuration testing
2. **Use AI for Finals**: Enable AI for routes you'll actually deploy
3. **Batch Questions**: Ask multiple related questions in sequence rather than re-optimizing
4. **Monitor Usage**: Set up spending alerts in Anthropic console
5. **Choose Right Model**: Sonnet 4.5 is sufficient for 95% of use cases

---

## Support

### AI Feature Issues

For AI-specific problems:
- Check Anthropic status: [status.anthropic.com](https://status.anthropic.com)
- Review API documentation: [docs.anthropic.com](https://docs.anthropic.com)
- Verify API key at: [console.anthropic.com](https://console.anthropic.com)

### General App Issues

For routing or app problems:
- See SETUP.md troubleshooting section
- Check Google Maps API quota
- Review logs in terminal where Streamlit is running

---

## Future AI Features (Roadmap)

Potential enhancements under consideration:

- **Multi-Vehicle AI**: Explain trade-offs across multiple vehicle routes
- **Historical Analysis**: "How does this route compare to last week?"
- **Predictive Suggestions**: "Based on patterns, consider prioritizing orders in sector X"
- **CSV Validation**: AI-powered data quality checks on upload
- **Driver Feedback Loop**: Integrate actual route performance to improve predictions
- **Voice Interface**: Ask questions via speech instead of typing

---

**Built with Claude AI by Anthropic**
**Model**: Claude Sonnet 4.5 (February 2026)
**Documentation Version**: 1.0
