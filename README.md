# Assignment 2: Compare & Contrast — Dual Implementation of an Expense Approval Workflow

**Student:** Bryan Edler  
**Student Number:** 041016930  
**Course:** CST8917 - Serverless Applications  
**Project Title:** Dual Implementation of an Expense Approval Pipeline: Durable Functions vs. Logic Apps  
**Date:** August 11, 2026  

---

## Version A Summary — Durable Functions (Code-First)

My Durable Functions implementation uses the Python v2 programming model. The workflow has three main parts:

**Client Function:** This is an HTTP trigger that starts a new orchestration instance when someone submits an expense. It takes the expense data, validates required fields are present, and kicks off the orchestrator.

**Orchestrator Function:** This manages the entire workflow. It calls activity functions in sequence, handles the manager approval step (including the timeout timer), and decides the final outcome. The orchestrator is stateful — it remembers where it is in the workflow even if there's a delay waiting for manager input.

**Activity Functions:** These do the actual work:
- `validate_expense`: Checks that all required fields exist and the category is valid
- `process_auto_approval`: Handles expenses under $100
- `wait_for_manager`: Starts the manager approval process with a 24-hour timeout
- `send_notification`: Sends email to the employee with the final decision

**Human Interaction Pattern:** For manager approval, the orchestrator creates a durable timer and waits for an external event (the manager's decision). If the manager responds before the timer expires, the orchestrator continues based on that decision. If the timer expires first, the expense is auto-approved and flagged as "escalated".

**HTTP Endpoint for Manager:** A separate HTTP trigger function allows managers to approve or reject by calling `http://localhost:7071/api/manager/{instanceId}?decision=approve`.

**Testing:** I used the `test-durable.http` file with VS Code's REST Client extension to test all six scenarios. Each test starts a new orchestration and I can track the status through the logs.

**Key Challenge:** The trickiest part was understanding the async pattern with `call_activity`, `create_timer`, and `wait_for_external_event`. I initially tried to use `asyncio.sleep()` but learned that durable timers are needed because they persist across function restarts.

---

## Version B Summary — Logic Apps + Service Bus (Visual/Declarative)

My Logic Apps implementation uses a different approach since Logic Apps doesn't have a built-in "wait for external event" pattern like Durable Functions.

**Service Bus Queue:** This is the entry point. Anyone can submit an expense by sending a JSON message to this queue. This decouples the submission from the processing.

**Logic App Trigger:** The Logic App starts automatically when a message arrives in the queue. It reads the expense data and begins the workflow.

**Validation Function:** Instead of doing validation directly in the Logic App, I created an Azure Function that validates the expense. The Logic App calls this function using the "Azure Functions" action. This keeps the logic reusable and easier to test.

**Manager Approval Approach:** Since Logic Apps can't wait indefinitely for a human response, I used a different pattern:
- The Logic App sends an email to the manager with a link to approve or reject
- The link includes the instance ID and choice in the URL
- A separate HTTP-triggered Azure Function receives the manager's decision and stores it in Azure Table Storage
- The Logic App has a "Delay until" action that waits for a set time (24 hours), then checks Table Storage for the manager's decision
- If a decision exists, it uses that; if not, it escalates

**Service Bus Topic with Subscriptions:** Instead of direct email notifications, I send the final outcome to a Service Bus topic. Three filtered subscriptions (approved, rejected, escalated) route messages to different processing paths. This makes it easy to add new handlers later (like logging or reporting) without changing the main Logic App.

**Testing:** I used the `test-expense.http` file to send test messages to the Service Bus queue. I captured screenshots of the Logic App run history, which shows each step and whether it succeeded or failed.

**Key Challenge:** The "wait for manager" step was the biggest design decision. Logic Apps has a "Delay until" action, but it only waits for a fixed time. My solution with Table Storage and a polling approach works but feels less elegant than Durable Functions' event waiting pattern.

---

## Comparison Analysis (Full 800-1200 words)

### 1. Development Experience

**Which was faster to build?** Logic Apps was faster to get started. I could drag and drop actions, and the visual designer made it clear what the workflow looked like. For a simple workflow like validation → decision → notification, I had a working version in about half the time it took for Durable Functions.

But Durable Functions was faster when I needed to make changes. When I wanted to adjust the validation logic or add a new category, I just changed a Python function and redeployed. With Logic Apps, I had to click through the designer, find the right connector, and sometimes reconfigure connections between steps. The visual approach gets tedious when you have many steps.

**Easier to debug?** Durable Functions wins here. I could run everything locally using the Azure Functions Core Tools. I could set breakpoints in VS Code, step through the code, and inspect variables. The logs showed me exactly what each activity function returned and what the orchestrator decided.

Logic Apps debugging was frustrating. The run history shows each action and its inputs/outputs, which is helpful, but you can't step through it. When something failed, I often had to guess why. The error messages are generic — "Action failed" with a status code, but not always clear what went wrong. I spent more time trial-and-error testing with Logic Apps.

**Which gave more confidence the logic was correct?** Durable Functions gave me more confidence because I could write unit tests for the activity functions. The orchestrator logic is just Python code, so I could mentally trace through the flow. With Logic Apps, I had to trust the visual designer and test everything end-to-end.

### 2. Testability

**Which was easier to test locally?** Durable Functions, without question. I tested all six scenarios locally using HTTP requests. I could see the orchestrator progress in the terminal and verify each outcome. The `test-durable.http` file let me run all tests in sequence.

For Logic Apps, local testing is basically impossible. You have to deploy to Azure and test against real resources. This means every test run takes longer and costs money (though small amounts). I tested by sending messages to the Service Bus queue and watching the Logic App runs in the Azure portal.

**Could you write automated tests?** Yes for both, but differently. For Durable Functions, I could write Python unit tests with pytest, mocking the activity functions. The orchestrator is deterministic, so I could test different paths.

For Logic Apps, automated testing would mean deploying to a test environment and using the REST API to trigger runs and check outcomes. It's possible but more complex. The visual nature makes it harder to automate because you're testing through the Azure platform, not code.

### 3. Error Handling

**How does each handle failures?** Both have retry policies, but they work differently.

Durable Functions gives me fine-grained control. I can add retry policies to individual activity calls using `RetryOptions`. If validation fails because of a transient issue, it retries. If it fails permanently, I can catch the error in the orchestrator and decide what to do — maybe send a notification about the failure.

Logic Apps has built-in retry policies for most actions. You can configure the number of retries and the interval. But it's a global setting per action, not as flexible. If a failure occurs, the Logic App stops and marks the run as failed. You can add "Configure run after" settings to handle failures (like sending an alert), but it's more cumbersome than try/except in code.

**Which gives more control?** Durable Functions gives much more control. I can add error handling at any point in the orchestrator. For example, if the manager approval fails, I can log it, send an alert, and maybe retry with a different manager. With Logic Apps, once a step fails, the workflow typically stops unless you explicitly handle it.

### 4. Human Interaction Pattern

**How did each handle "wait for manager approval"?** This was the biggest difference.

Durable Functions has a natural pattern for this: `wait_for_external_event` + `create_timer`. The orchestrator waits for the manager's decision, and if the timer expires first, it escalates. The wait is stateful — if the function unloads and reloads (which happens in serverless), the wait persists.

Logic Apps doesn't have an equivalent. I had to implement a polling solution: the Logic App delays 24 hours, then checks a table for the manager's decision. This works but has drawbacks:
- The Logic App stays in the "Running" state for the entire 24 hours, which could be expensive
- If the manager responds after the delay, it's too late
- The Logic App can't be "woken up" by the manager's response — it just checks once when the delay ends

**Which was more natural?** Durable Functions was more natural. The code reads like a story: "Wait for manager response, but if we don't hear back in 24 hours, escalate." The Logic Apps approach feels like a workaround, which it is.

### 5. Observability

**Which made it easier to monitor runs?** Logic Apps has a beautiful run history view in the Azure portal. You can see every action, its inputs and outputs, start and end times, and any errors. The visual flow highlights which steps succeeded and which failed. This is great for operations teams who aren't developers.

Durable Functions also has monitoring through Application Insights, but it's not as visual. You see traces, not a diagram. The orchestrator functions generate events that show up in Application Insights, but you need to query them.

**Which made it easier to diagnose problems?** For a developer, Durable Functions was better because the logs show exactly what each activity did. I could enable verbose logging and see the function execution details. For a non-developer, Logic Apps would be easier — the run history speaks for itself.

### 6. Cost

I used the Azure Pricing Calculator with these assumptions:
- Each expense request triggers one orchestration/Logic App run
- Activity functions run for about 500ms each
- Memory usage is 256MB for Functions, 1GB for Logic Apps
- Storage costs are minimal (ignore for this estimate)

**At ~100 expenses/day (3,000/month):**
- Durable Functions: ~$0.50/month (executions + storage)
- Logic Apps: ~$12/month (standard tier, 3,000 runs)
- Winner: Durable Functions

**At ~10,000 expenses/day (300,000/month):**
- Durable Functions: ~$5/month (executions + storage)
- Logic Apps: ~$120/month (standard tier, 300,000 runs)
- Winner: Durable Functions by a large margin

Logic Apps is priced per run, while Functions is priced per execution time and memory. For high-volume workflows, Functions is significantly cheaper. However, Logic Apps includes many connectors (Service Bus, email, etc.) in the price, while Functions would need additional Azure services that add cost.

---

## Recommendation (200-300 words)

If a team asked me to build this for production, I would choose **Durable Functions** for this specific workflow. Here's why:

**1. Cost:** At ~100 expenses/day, the cost difference is small, but at higher volumes, Durable Functions is much cheaper. If the company grows, this matters.

**2. Maintainability:** The Python code is easier to version control, review in pull requests, and modify. I can add new features (like a second approval level) just by changing the orchestrator code.

**3. Control:** I have complete control over error handling, retries, and the human interaction pattern. The timeout + external event pattern is elegant and reliable.

**4. Testing:** Being able to test locally and write unit tests gives me confidence in the code.

**When would I choose Logic Apps instead?**

If the team was mostly non-developers (business analysts, operations) who need to understand and modify the workflow, Logic Apps would be better. The visual designer makes it accessible. Also, if we needed many integrations with Microsoft 365 (SharePoint, Teams, Outlook, etc.), Logic Apps has built-in connectors that would save development time.

I would also choose Logic Apps for simple, straight-through workflows that don't need complex state management or long-running waits. But for any workflow with human interaction and timeouts, Durable Functions is the better choice.

---


##  Video Demo
[Video Demo Link](https://youtu.be/63xIbwPnfe4)

## References

1. Microsoft Learn. (2026). "Durable Functions Overview." https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-overview

2. Microsoft Learn. (2026). "Azure Logic Apps Overview." https://learn.microsoft.com/en-us/azure/logic-apps/logic-apps-overview

3. Microsoft Learn. (2026). "Human Interaction in Durable Functions." https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-phone-verification

4. Microsoft Learn. (2026). "Azure Functions Python Developer Guide." https://learn.microsoft.com/en-us/azure/azure-functions/functions-reference-python

5. Microsoft Learn. (2026). "Azure Service Bus Messaging." https://learn.microsoft.com/en-us/azure/service-bus-messaging/

6. Azure Pricing Calculator. (2026). https://azure.microsoft.com/en-us/pricing/calculator/

---

## AI Disclosure

AI tools (ChatGPT) were used for the following purposes:
- Brainstorming the architecture for both versions
- Generating the initial structure for the comparison analysis
- Debugging help with Python async patterns in Durable Functions
- Proofreading and suggesting improvements to this document

