import typing

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.requests import Request
from starlette.middleware import Middleware
from starlette.background import BackgroundTask
from starlette.middleware.cors import CORSMiddleware
from payments_service import service


def home(request: Request):
    return JSONResponse({"hello": "world"})


async def payment_credentials(request: Request):
    identifier = request.query_params.get("identifier")
    if not identifier:
        return JSONResponse(
            {"status": False, "msg": "Missing `identifier` as query params"}
        )
    result = await service.post(identifier)
    if result:
        return JSONResponse({"status": True, "data": result})
    return JSONResponse({"status": False, "msg": "Error fetching credentials"})


async def webhook_callback(request: Request):
    signature = request.headers.get("verif-hash")
    body = await request.body()
    async def task():
        payment_instance = await service.build_payment_instance(signature)
        if payment_instance:
            payment_instance.instance.webhook_api.verify(
                signature,
                body,
                full_auth=True,
                full=False,
                callback_func=payment_instance.webhook_callback_func,
            )

    return JSONResponse({"status": "Success"}, background=BackgroundTask(task))


async def generate_payment_account_no(request: Request):
    identifier = request.path_params["identifier"]
    params = await request.json()
    account_name = params.get("account_name")
    client_email = params.get("client_email")
    permanent = params.get("permanent")
    order = params.get("order")
    if account_name and client_email:
        payment_instance = await service.build_payment_instance(identifier)
        response = payment_instance.instance.transaction_api.create_payment_account(
            account_name, client_email, is_permanent=permanent
        )
        if response[0]:
            return JSONResponse(
                {"status": True, "msg": response[1], "data": response[2]}
            )
        return JSONResponse({"status": False, "msg": response[1]}, status_code=400)
    return JSONResponse(
        {"status": False, "msg": "Missing account name or client email"},
        status_code=400,
    )


async def verify_payment(request: Request):
    identifier = request.path_params["identifier"]
    amount = request.query_params.get("amount")
    ref = request.query_params.get("txref")
    amount_only = request.query_params.get("amount_only") or ""
    if amount and ref:
        a_only = amount_only.lower().strip() == "true"
        payment_instance = await service.build_payment_instance(identifier)
        result = payment_instance.instance.verify_payment(
            ref, amount=amount, amount_only=a_only
        )
        if result[0]:
            if a_only:
                return JSONResponse({"status": result[0], "msg": result[1]})
            return JSONResponse(
                {"status": result[0], "msg": result[1], "data": result[2]}
            )
        return JSONResponse({"status": False, "msg": "Verification Failed"})
    return JSONResponse(
        {"status": False, "msg": "missing `amount` or txref` query parameters"},
        status_code=400,
    )


async def client_payment_object(request: Request):
    identifier = request.path_params["identifier"]
    body = await request.json()
    amount = body.get("amount")
    currency = body.get("currency")
    order_id = body.get("order")
    user_info = body.get("user") or {}
    processor_info = body.get("processor_info") or {}

    payment_instance = await service.build_payment_instance(identifier)
    if not all([amount, order_id]):
        return JSONResponse(
            {"status": False, "msg": "missing `amount` or `order`"}, status_code=400
        )
    redirect_url = payment_instance.build_redirect_url(amount, order_id)
    obj = payment_instance.instance.processor_info(amount, redirect_url=redirect_url)
    other_info = payment_instance.instance.other_payment_info(
        currency=currency,
        **{
            **user_info,
            "order": order_id,
            "callback_url": redirect_url,
            "amount": amount,
            **processor_info,
        }
    )
    return JSONResponse(
        {
            "status": True,
            "data": {
                "processor_button_info": other_info,
                "payment_obj": obj,
                "kind": payment_instance.kind,
            },
        }
    )


middlewares = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_headers=["*"],
        allow_methods=["*"],
        allow_credentials=True,
    )
]

routes = [
    Route("/", home),
    # Route("/credentials", payment_credentials),
    Route("/webhook", webhook_callback, methods=["POST"]),
    Route("/verify-payment/{identifier}", verify_payment),
    Route(
        "/generate-account-no/{identifier}",
        generate_payment_account_no,
        methods=["POST"],
    ),
    Route("/build-payment-info/{identifier}", client_payment_object, methods=["POST"]),
]

app = Starlette(middleware=middlewares, routes=routes)
