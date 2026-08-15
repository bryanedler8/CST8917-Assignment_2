import json
import logging
from datetime import datetime, timedelta
import azure.functions as func
import azure.durable_functions as df

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

VALID_CATEGORIES = ["travel", "meals", "supplies", "equipment", "software", "other"]
TIMEOUT_HOURS = 24

@app.route(route="start")
@app.durable_client_input(client_name="client")
async def http_start(req: func.HttpRequest, client: df.DurableOrchestrationClient):
    try:
        req_body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON body"}),
            status_code=400,
            mimetype="application/json"
        )
    
    required_fields = ["employee_name", "employee_email", "amount", "category", "description", "manager_email"]
    missing_fields = [field for field in required_fields if field not in req_body]
    if missing_fields:
        return func.HttpResponse(
            json.dumps({"error": f"Missing required fields: {', '.join(missing_fields)}"}),
            status_code=400,
            mimetype="application/json"
        )
    
    instance_id = await client.start_new("expense_orchestrator", None, req_body)
    logging.info(f"Started orchestration with ID: {instance_id}")
    return client.create_check_status_response(req, instance_id)

@app.orchestration_trigger(context_name="context")
def expense_orchestrator(context: df.DurableOrchestrationContext):
    expense = context.get_input()
    validation_result = yield context.call_activity("validate_expense", expense)
    
    if not validation_result["valid"]:
        notification = {
            "email": expense["employee_email"],
            "employee_name": expense["employee_name"],
            "amount": expense["amount"],
            "category": expense["category"],
            "status": "rejected",
            "reason": validation_result["error"],
            "is_escalated": False
        }
        yield context.call_activity("send_notification", notification)
        return notification
    
    amount = float(expense["amount"])
    if amount < 100:
        notification = {
            "email": expense["employee_email"],
            "employee_name": expense["employee_name"],
            "amount": amount,
            "category": expense["category"],
            "status": "approved",
            "reason": "Auto-approved (under $100)",
            "is_escalated": False
        }
        yield context.call_activity("send_notification", notification)
        return notification
    
    manager_notification = {
        "email": expense["manager_email"],
        "employee_name": expense["employee_name"],
        "employee_email": expense["employee_email"],
        "amount": amount,
        "category": expense["category"],
        "description": expense["description"],
        "status": "pending_approval",
        "instance_id": context.instance_id
    }
    yield context.call_activity("send_manager_request", manager_notification)
    
    timeout_time = context.current_utc_datetime + timedelta(hours=TIMEOUT_HOURS)
    timeout_task = context.create_timer(timeout_time)
    manager_task = context.wait_for_external_event("ManagerDecision")
    
    winner = yield context.task_any([timeout_task, manager_task])
    
    if winner == timeout_task:
        notification = {
            "email": expense["employee_email"],
            "employee_name": expense["employee_name"],
            "amount": amount,
            "category": expense["category"],
            "status": "approved",
            "reason": f"Auto-approved after {TIMEOUT_HOURS}h timeout (manager did not respond)",
            "is_escalated": True
        }
        yield context.call_activity("send_notification", notification)
        if not timeout_task.is_completed:
            timeout_task.cancel()
        return notification
    else:
        manager_decision = manager_task.result
        if not timeout_task.is_completed:
            timeout_task.cancel()
        
        if manager_decision == "approve":
            notification = {
                "email": expense["employee_email"],
                "employee_name": expense["employee_name"],
                "amount": amount,
                "category": expense["category"],
                "status": "approved",
                "reason": "Approved by manager",
                "is_escalated": False
            }
        else:
            notification = {
                "email": expense["employee_email"],
                "employee_name": expense["employee_name"],
                "amount": amount,
                "category": expense["category"],
                "status": "rejected",
                "reason": "Rejected by manager",
                "is_escalated": False
            }
        yield context.call_activity("send_notification", notification)
        return notification

@app.activity_trigger(input_name="expense")
def validate_expense(expense: dict) -> dict:
    required_fields = ["employee_name", "employee_email", "amount", "category", "description", "manager_email"]
    for field in required_fields:
        if field not in expense or not expense[field]:
            return {"valid": False, "error": f"Missing or empty field: {field}"}
    try:
        amount = float(expense["amount"])
        if amount <= 0:
            return {"valid": False, "error": "Amount must be greater than 0"}
    except ValueError:
        return {"valid": False, "error": "Amount must be a valid number"}
    if expense["category"].lower() not in VALID_CATEGORIES:
        return {"valid": False, "error": f"Invalid category. Must be one of: {', '.join(VALID_CATEGORIES)}"}
    return {"valid": True}

@app.activity_trigger(input_name="notification")
def send_notification(notification: dict) -> str:
    logging.info(f"EMAIL NOTIFICATION: To: {notification['email']}, Status: {notification['status']}")
    return f"Notification sent to {notification['email']}"

@app.activity_trigger(input_name="request")
def send_manager_request(request: dict) -> str:
    logging.info(f"MANAGER REQUEST: To: {request['email']}, Amount: ${request['amount']}")
    return f"Manager request sent to {request['email']}"

@app.route(route="manager/{instanceId}")
@app.durable_client_input(client_name="client")
async def manager_decision(req: func.HttpRequest, client: df.DurableOrchestrationClient):
    instance_id = req.route_params.get("instanceId")
    try:
        req_body = req.get_json()
        decision = req_body.get("decision", "").lower()
    except ValueError:
        return func.HttpResponse(json.dumps({"error": "Invalid JSON body"}), status_code=400, mimetype="application/json")
    if decision not in ["approve", "reject"]:
        return func.HttpResponse(json.dumps({"error": "Decision must be 'approve' or 'reject'"}), status_code=400, mimetype="application/json")
    await client.raise_event(instance_id, "ManagerDecision", decision)
    return func.HttpResponse(json.dumps({"message": f"Decision '{decision}' sent to expense {instance_id}"}), status_code=200, mimetype="application/json")
