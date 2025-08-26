import requests
from frappe.utils import today, add_months, formatdate, getdate
import frappe
import urllib.parse
import json

customers = frappe.get_all(
    'Customer', 
    filters={"service": "ERP", "disabled": 0, "is_frozen": 0},
    fields=["customer_name", "custom_url", "custom_api_key", "custom_api_secret", 
            "custom_pricing_model", "email_id", "default_price_list", 
            "default_currency", "custom_server_charge"]
)

current_date_str = today()
current_date = getdate(current_date_str)
#previous_date = add_months(current_date, -1)
previous_month_year = f'{current_date.strftime("%B").upper()} {current_date.strftime("%Y")}'

for customer in customers:
    if customer["customer_name"] != "zlquetzal.business-dev.emolus.com":
        continue
    
    print(customer["customer_name"])
    
    api_key = customer['custom_api_key']
    api_secret = customer['custom_api_secret']
    base_url = customer['custom_url']
    endpoint = '/api/method/frappe.auth.get_logged_user'
    url = base_url + endpoint

    headers = {
        'Authorization': f'token {api_key}:{api_secret}',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }

    try:
        response = requests.get(url, headers=headers)
    except Exception as e:
        frappe.log_error(f"Error autenticando {customer['customer_name']}: {str(e)}")
        continue

    if customer["custom_pricing_model"] == "User":
        params = {
            'fields': '["name","email"]',
            'filters': '[["enabled","=",1],["email","not like", "%example.com%"],'
                       '["email","not like", "%emolus.com%"],'
                       '["email","not like", "%erpnext.com%"],'
                       '["email","not like", "%luis-pinillos@hotmail.com%"],'
                       '["owner","not in", ["Guest"]],'
                       '["user_type","=", "System User"]]'
        }
    elif customer["custom_pricing_model"] == "Company":
        params = {
            'fields': '["company_name"]',
        }

    item_code = customer["custom_pricing_model"].upper()
    url = f"{base_url}/api/resource/{customer['custom_pricing_model']}"

    try:
        response_data = requests.get(url, headers=headers, params=params)        
        items_list = response_data.json().get("data", [])
        filtered_users = []
        added_emails = set()       
        for user in items_list:
            user_name = user['name'] 
            user_url = f"{base_url}/api/resource/User/{user_name}?fields=[%22roles%22]"

            user_roles_response = requests.get(user_url, headers=headers)

            if user_roles_response.status_code == 200:
                roles_data = user_roles_response.json().get("data", []).get("roles", [])
                user_roles = {role["role"] for role in roles_data}
        
                has_user = "Restaurant User" in user_roles
                has_cashier = "Restaurant Cashier" in user_roles
                has_manager = "Restaurant Manager" in user_roles
                
                if (
                    not has_user and not has_cashier               # Caso 1: no tiene ninguno
                    or (has_user and has_cashier)                  # Caso 2: tiene ambos
                    or (has_user and has_manager)                  # Caso 3: tiene User y Manager
                ):
                    filtered_users.append(user)   
        
        if filtered_users:
            items_list = filtered_users

    except Exception as e:
        frappe.log_error(f"Error obteniendo datos de {customer['customer_name']}: {str(e)}")
        continue

    description = f"FOR ACTIVE USERS IN {previous_month_year}\n"
    for item in items_list:
        description += f"{item['email']}\n"

    items_length = len(items_list)
    rates = frappe.get_all('Item Price', filters={
        'price_list': customer['default_price_list'], 
        'item_code': item_code, 
        'selling': 1,
        'customer': ["in", ["", customer['customer_name']]]  # Se usa 'in' para buscar ambos valores
    }, limit_page_length=2, order_by="creation desc")
    
    rate = None  # Aseguramos que 'rate' esté inicializado en None
    
    for rate_i in rates:
        if rate_i.get('customer'):  # Verificamos si el campo 'customer' tiene un valor
            rate = rate_i
            break
    
    if not rate and rates:
        rate = rates[0]
    items = [{
        'item_code': item_code,
        'item_name': item_code,
        'description': description,
        'qty': items_length,
        'rate': rate.price_list_rate,
        'income_account': 'Sales - emolu',
        'expense_account': 'Cost of Goods Sold - emolu',
        'cost_center': 'Profit and Losses - emolu'
    }]

    if customer["custom_server_charge"] == 1:
        rate = frappe.get_last_doc('Item Price', filters={
            'price_list': customer['default_price_list'], 
            'item_code': 'SERVER'
        })
        items.append({
            'item_code': 'SERVER',
            'item_name': 'SERVER',
            'description': f'ERP SERVER {previous_month_year}',
            'qty': 1,
            'rate': rate.price_list_rate,
            'income_account': 'Sales - emolu',
            'expense_account': 'Cost of Goods Sold - emolu',
            'cost_center': 'Profit and Losses - emolu'
        })

    new_invoice = frappe.get_doc({
        'doctype': 'Sales Invoice',
        'customer': customer["customer_name"],
        'posting_date': frappe.utils.now(),
        'business_unit': "ERP",
        'cost_center': 'Balance Sheet - emolu',
        'items': items,
        'docstatus': 1
    })
    new_invoice.insert()

    if new_invoice.name:
        frappe.msgprint(f"Se emitió la factura {new_invoice.name} del cliente {customer['customer_name']}")

        new_payment_request = frappe.get_doc({
            'doctype': 'Payment Request',
            'payment_request_type': 'Inward',
            'mode_of_payment': 'Stripe',
            'party_type': 'Customer',
            'party': customer["customer_name"],
            'reference_doctype': 'Sales Invoice',
            'reference_name': new_invoice.name,
            'grand_total': new_invoice.grand_total,
            'currency': new_invoice.currency,
            'payment_gateway_account': 'Stripe-Stripe - USD',
            'print_format': 'Emolus',
            'subject': 'Payment Request for ' + new_invoice.name,
            'description': 'Payment Request for ' + new_invoice.name,
            'email_to': customer["email_id"],
            'docstatus': 1,
            'message': '<meta charset="UTF-8"> <meta name="viewport"> <meta name="x-apple-disable-message-reformatting"> <meta> <meta name="format-detection"> <link href="https://fonts.googleapis.com/css?family=Roboto:400,400i,700,700i" rel="stylesheet"> <div class="es-wrapper-color"> <table cellpadding="0" cellspacing="0" class="es-wrapper" width="100%"> <tbody> <tr> <td class="esd-email-paddings st-br" valign="top"> <table align="center" cellpadding="0" cellspacing="0" class="es-header esd-header-popover"> <tbody> <tr> <td align="center" bgcolor="transparent" class="esd-stripe esd-checked" style="background-color: transparent;"> <div> <table align="center" bgcolor="transparent" cellpadding="0" cellspacing="0" class="es-header-body" style="background-color: transparent;" width="600"> <tbody> <tr> <td align="left" class="esd-structure es-p20t es-p20r es-p20l"> <table cellpadding="0" cellspacing="0" width="100%"> <tbody> <tr> <td align="center" class="esd-container-frame" valign="top" width="560"> <table cellpadding="0" cellspacing="0" width="100%"> <tbody> <tr> <td align="center" class="esd-block-image" style="font-size: 0px;"><a href="https://www.emolus.com" target="_blank"><img alt="" src="https://www.emolus.com/wp-content/uploads/2020/06/Logo-e1592069868140.png" style="display: block; width: 175px; height: 61px;" width="175"></a></td></tr><tr> <td align="center" class="esd-block-spacer" height="65"></td></tr></tbody> </table> </td></tr></tbody> </table> </td></tr></tbody> </table> </div></td></tr></tbody> </table> <table align="center" cellpadding="0" cellspacing="0" class="es-content"> <tbody> <tr> <td align="center" bgcolor="transparent" class="esd-stripe" style="background-color: transparent;"> <table align="center" bgcolor="transparent" cellpadding="0" cellspacing="0" class="es-content-body" style="background-color: transparent;" width="600"> <tbody> <tr> <td align="left" bgcolor="#ffffff" class="esd-structure es-p30t es-p15b es-p30r es-p30l" style="border-radius: 10px 10px 0px 0px; background-color: #ffffff; background-position: left bottom; width: 100%;"> <table cellpadding="0" cellspacing="0" width="100%"> <tbody> <tr> <td align="center" class="esd-container-frame" valign="top" width="540"> </td></tr><tr> <td align="left" class="esd-block-text es-p20t"></td></tr><tr><td align="left" class="esd-container-frame" valign="top" width="540"> <p><span style="font-family: Montserrat; font-size: 14px; color: #444444;">Hola {{doc.contact_person}}:</span></p><p><span style="font-family: Montserrat; font-size: 14px; color: #444444;">Adjunto encontrarás la factura #{{doc.name}} por concepto servicio de PBX para {{doc.customer}} por un monto de {{doc.currency}} {{doc.grand_total}}.</span></p><p><span style="font-family: Montserrat; font-size: 14px; color: #444444;">Sigue el enlace para efectuar el pago de la factura:</span></p><center><p><br><span style="width: 50%; border: none; text-align: center; color: #ffffff; margin: 0px; font-size: 16px; font-weight: bold; padding: 18px 0px; font-family: Arial; border-radius: 30px; background: #f46e1e;"><a href="{{payment_url}}"><span style="width: 50%; border: none; text-align: center; color: #ffffff; margin: 0px; font-size: 16px; font-weight: bold; padding: 18px 0px; font-family: Lato, sans-serif; text-decoration: inherit; margin: 0 20px;">Pagar factura # {{doc.currency}} {{doc.grand_total}}</span></a></span></p></center><br><p><span style="font-family: Montserrat; font-size: 14px; color: #444444;">Cualquier pregunta no dudes en contactarnos</span></p><p><span style="font-family: Montserrat; font-size: 14px; color: #444444;">El equipo de Emolus</span></p></td></tr></tbody> </table> </td></tr><tr> <td align="left" class="esd-structure" style="border-radius: 0px 0px 10px 10px; background-position: center bottom; background-color: #ffffff;"> <table cellpadding="0" cellspacing="0" width="100%"> <tbody> <tr> <td align="center" class="esd-container-frame" valign="top" width="600"> <table cellpadding="0" cellspacing="0" width="100%"> <tbody> <tr> <td align="center" class="esd-block-text es-p5b es-m-txt-c"><br></td></tr><tr> <td align="center" class="esd-block-spacer" height="15"></td></tr></tbody> </table> </td></tr></tbody> </table> </td></tr></tbody> </table> </td></tr></tbody> </table> <table align="center" cellpadding="0" cellspacing="0" class="esd-footer-popover es-footer"> <tbody> <tr> <td align="center" background="https://new.emolus.com/wp-content/uploads/2020/06/background_prices_emolus.png" bgcolor="#fff" class="esd-stripe esd-checked" height="230px" style="background-repeat: no-repeat; background-position: center bottom; background-color: #ffffff;"> <table align="center" cellpadding="0" cellspacing="0" class="es-footer-body" width="600"> <tbody> <tr> <td align="left" class="esd-structure es-p10t es-p20b es-p30r es-p30l"> <table cellpadding="0" cellspacing="0" width="100%"> <tbody> <tr> <td align="center" class="esd-container-frame" valign="top" width="540"> <table cellpadding="0" cellspacing="0" width="100%"> <tbody> <tr> <td align="center" class="esd-block-spacer es-p20" style="font-size: 0;"> <table border="0" cellpadding="0" cellspacing="0" height="100%" width="100%"> <tbody> <tr> <td style="background: none; height: 1px; width: 100%; margin: 0px 0px 0px 0px;"></td></tr></tbody> </table> </td></tr><tr> <td align="center" class="esd-block-text es-p5b es-m-txt-c"> <p><a href="https://www.emolus.com/"><span style="font-size: 12px; font-family: arial; color: #707070; text-decoration: inherit;">Sobre Nosotros</span></a> | <a href="https://www.emolus.com/"><span style="font-size: 12px; font-family: arial; color: #707070; text-decoration: inherit;">Términos y condiciones</span></a> | <a href="https://www.emolus.com/"><span style="font-size: 12px; font-family: arial; color: #707070; text-decoration: inherit;">Política de Privacidad</span></a></p><br><p style="font-size: 12px; font-family: arial; color: #707070;">&copy; 2021, Emolus LLC. 8423 NW 68th Street, Miami Fl. 33166 Todos los derechos reservados Recibiste este correo por que aplicaste a Emolus como proveedor del servicio de PBX corporativo</p></td></tr></tbody> </table> </td></tr></tbody> </table> </td></tr><tr> <td align="left" class="esd-structure es-p30t es-p30b es-p30r es-p30l" style="border-radius: 0px 0px 10px 10px;"> <table align="left" cellpadding="0" cellspacing="0" class="es-left"> <tbody> <tr> <td align="center" class="es-m-p0r es-m-p20b esd-container-frame" width="166"> <table cellpadding="0" cellspacing="0" width="100%"> <tbody> <tr> <td align="center" class="esd-empty-container" style="display: none;"></td></tr></tbody> </table> </td><td class="es-hidden" width="20"></td></tr></tbody> </table> <table align="left" cellpadding="0" cellspacing="0" class="es-left"> <tbody> <tr> <td align="center" class="esd-container-frame" width="165"> <table cellpadding="0" cellspacing="0" width="100%"> <tbody> <tr> <td align="left" class="esd-block-social es-m-txt-c" style="font-size: 0;"> <table cellpadding="0" cellspacing="0" class="es-table-not-adapt es-social"> <tbody> <tr> <td align="center" class="es-p10r" valign="top"><a href="" target="_blank"><img alt="Fb" src="https://www.emolus.com/wp-content/uploads/2020/06/facebook-logo-black.png" title="Facebook" width="32"></a></td><td align="center" class="es-p10r" valign="top"><a href="" target="_blank"><img alt="Tw" src="https://www.emolus.com/wp-content/uploads/2020/06/twitter-logo-black.png" title="Twitter" width="32"></a></td></tr></tbody> </table> </td></tr></tbody> </table> </td></tr></tbody> </table> <table align="right" cellpadding="0" cellspacing="0" class="es-right"> <tbody> <tr> <td align="center" class="esd-container-frame" width="169"> <table cellpadding="0" cellspacing="0" width="100%"> <tbody> <tr> <td align="center" class="esd-empty-container" style="display: none;"></td></tr></tbody> </table> </td></tr></tbody> </table> </td></tr><tr> <td align="left" class="esd-structure" style="background-position: left top;"> <table cellpadding="0" cellspacing="0" width="100%"> <tbody> <tr> <td align="center" class="esd-container-frame" valign="top" width="600"> <table cellpadding="0" cellspacing="0" width="100%"> <tbody> <tr> <td align="center" class="esd-block-spacer" height="40"></td></tr></tbody> </table> </td></tr></tbody> </table> </td></tr></tbody> </table> </td></tr></tbody> </table> </td></tr></tbody> </table> </div>',
        })
        new_payment_request.insert()
        if new_payment_request.name:
            frappe.msgprint(f"Se emitió la el requerimiento de pago {new_payment_request.name}  del cliente {customer['customer_name']}" )
        else:
            frappe.log_error(title="New Payment Request Error", message=f"ERP: {customer['customer_name']} {previous_month_year}")
    else:
        frappe.log_error(title="New Invoice Error", message=f"ERP: {customer['customer_name']} {previous_month_year}")

frappe.db.commit()        
            