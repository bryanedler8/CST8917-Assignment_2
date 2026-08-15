import json
import azure.functions as func
import logging

app = func.FunctionApp()
VALID_CATEGORIES = ["travel", "meals", "supplies", "equipment", "software", "other"]

@app.route(route="validate-expense", methods=["POST"])
def validate_expense(req: func.HttpRequest) -> func.HttpResponse:
    try:
        expense = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"valid": False, "error": "Invalid JSON"}),
            status_code=200,
            mimetype="application/json"
        )
    
    required_fields = ["employee_name", "employee_email", "amount", "category", "description", "manager_email"]
    for field in required_fields:
        if field not in expense or not expense[field]:
            return func.HttpResponse(
                json.dumps({"valid": False, "error": f"Missing or empty field: {field}"}),
                status_code=200,
                mimetype="application/json"
            )
    
    try:
        amount = float(expense["amount"])
        if amount <= 0:
            return func.HttpResponse(
                json.dumps({"valid": False, "error": "Amount must be greater than 0"}),
                status_code=200,
                mimetype="application/json"
            )
    except ValueError:
        return func.HttpResponse(
            json.dumps({"valid": False, "error": "Amount must be a number"}),
            status_code=200,
            mimetype="application/json"
        )
    
    if expense["category"].lower() not in VALID_CATEGORIES:
        return func.HttpResponse(
            json.dumps({"valid": False, "error": f"Invalid category. Must be one of: {', '.join(VALID_CATEGORIES)}"}),
            status_code=200,
            mimetype="application/json"
        )
    
    return func.HttpResponse(
        json.dumps({"valid": True}),
        status_code=200,
        mimetype="application/json"
    )
