# -*- coding: utf-8 -*-
import uuid
import json
import base64
from datetime import datetime
from odoo import http, tools
from odoo.http import request

import logging
_logger = logging.getLogger(__name__)

class APICalls(http.Controller):

    @http.route('/api/sale_order/create', csrf=False, type="json", auth="public", methods=["POST"], cors="*")
    def create_sale_order(self, **kwargs):
        print('--create--sale--order--')
        try:
            post = request.httprequest.headers
            api_key = post.get("api_key")
            parameters = json.loads(http.request.httprequest.data)

            if api_key:
                user_id = request.env["res.users.apikeys"]._check_credentials(scope='rpc', key=api_key)
                if user_id:
                    partner_id = parameters.get('partner_id')
                    payment_vals = {}
                    partner = request.env['res.partner'].sudo().search([('h_id', '=', partner_id)], limit=1)

                    if not partner:
                        return {
                            "status": "False",
                            "message": "Partner ID not found",
                            "statusCode": 400,
                            "data": {}
                        }

                    journal_id = request.env['account.journal'].sudo().search([('name', '=', parameters.get('payment_method', False))], limit=1)
                    if journal_id:
                        payment_vals['journal_id'] = journal_id.id

                    parameters['partner_id'] = partner.id
                    sale_lines = parameters.pop('order_line', [])
                    processed_sale_lines = []

                    for line in sale_lines:
                        h_id = line.get('h_id')
                        product_uom_qty = line.get('product_uom_qty')
                        price_unit = line.get('price_unit')
                        # analytic_distribution = line.get('analytic_distribution')  # This should be a dict
                        product = request.env['product.product'].sudo().search([('h_id', '=', h_id)], limit=1)
                        if product:
                            sale_line_data = {
                                'product_id': product.id,
                                'product_uom_qty': product_uom_qty,
                                'price_unit': price_unit,
                            }
                            # if analytic_distribution:
                            # Create a dictionary for analytic distribution
                            analytic_distribution_dict = {}
                            # for analytic_account_name, percentage in analytic_distribution.items():
                            analytic_account = request.env['account.analytic.account'].sudo().search(
                                [('id', '=', '1')], limit=1
                            )
                            if not analytic_account:
                                # Create a new analytic account if not found
                                default_plan = request.env['account.analytic.plan'].sudo().create({'name': 'Default Plan'})
                                analytic_account = request.env['account.analytic.account'].sudo().create({
                                    'name': 'analytic_account_name',
                                    'plan_id': default_plan.id
                                })
                            analytic_distribution_dict[analytic_account.id] = 100
                            sale_line_data['analytic_distribution'] = analytic_distribution_dict
                            processed_sale_lines.append((0, 0, sale_line_data))
                        else:
                            return {
                                "status": "False",
                                "message": f"Product with H ID '{h_id}' not found",
                                "statusCode": 400,
                                "data": {}
                            }
                    parameters['order_line'] = processed_sale_lines
                    # Create the sale
                    if parameters.get('id', False):
                        parameters['h_id'] = parameters['h_id']
                        del parameters['id']
                    del parameters['payment_method']
                    sale = request.env['sale.order'].with_user(2).create(parameters)

                    sale.action_confirm()
                    if sale.picking_ids:
                        for picking in sale.picking_ids:
                            if picking.state not in ('done', 'cancel'):
                                picking.action_assign()
                                if picking.state != 'assigned':
                                    for move in picking.move_ids:
                                        if not move.move_line_ids:
                                            request.env['stock.move.line'].with_user(2).create({
                                                'move_id': move.id,
                                                'picking_id': picking.id,
                                                'product_id': move.product_id.id,
                                                'product_uom_id': move.product_uom.id,
                                                'qty_done': move.product_uom_qty,
                                                'location_id': move.location_id.id,
                                                'location_dest_id': move.location_dest_id.id,
                                            })
                                picking.button_validate()

                    if sale.sudo().mrp_production_ids:
                        for order in sale.sudo().mrp_production_ids:
                            order.button_mark_done()
                    invoice_id = sale._create_invoices()
                    invoice_id.write({'h_id':sale.h_id})
                    invoice_id.action_post()
                    if invoice_id:
                        payment_vals['payment_date'] = invoice_id.date
                    payment = request.env['account.payment.register'].with_context(active_model='account.move', active_ids=invoice_id.ids, default_group_payment=True, default_can_edit_wizard=True).sudo().create(payment_vals).sudo()._create_payments()
                    sale_data = []
                    if sale:
                        sale_data.append({
                            "order_id": sale.id,
                            "name": sale.name,
                            "date_order": sale.date_order,
                            "validity_date": sale.validity_date,
                            "state": sale.state,
                            "amount_total": sale.amount_total,
                            "order_line": [
                                {
                                    "product_id": line.product_id.id,
                                    "product_uom_qty": line.product_uom_qty,
                                    "price_unit": line.price_unit,
                                    "price_subtotal": line.price_subtotal,
                                    "analytic_distribution": {
                                        account_id: percentage
                                        for account_id, percentage in line.analytic_distribution.items()
                                    } if line.analytic_distribution else {}
                                } for line in sale.order_line
                            ]
                        })
                        response_data = {
                            "status": "True",
                            "statusCode": 200,
                            "data": sale_data
                        }
                        return response_data
                else:
                    dump = json.dumps({'error': str('Access token invalid !')})
                    return json.loads(dump)
            else:
                dump = json.dumps({'error': str('API key not found!')})
                return json.loads(dump)
        except Exception as e:
            unsuccess_data = {
                "status": "False",
                "message": str(e),
                "statusCode": 400,
                "data": {}
            }
            return unsuccess_data


    @http.route(['/api/products/read'], csrf=False, type="json", auth="public", methods=["GET"], cors="*")
    def get_product_list(self, **kwargs):
        try:
            post = request.httprequest.headers
            api_key = post.get("api_key")
            if api_key:
                user_id = request.env["res.users.apikeys"]._check_credentials(scope='rpc', key=api_key)
                if user_id:
                    product_ids = request.env['product.template'].sudo().search([])
                    product_list = []
                    for product in product_ids:
                        product_data = {
                            'name': product.name,
                            'product_id': product.id,
                            'default_code': product.default_code,
                            'type': product.type,
                            'h_id':product.h_id,
                        }
                        product_list.append(product_data)
                    dump = json.dumps({'data': product_list})
                    return json.loads(dump)
                else:
                    dump = json.dumps({'error': 'Access token invalid!'})
                    return json.loads(dump)
            else:
                data = {
                    "status": "False",
                    "statusCode": 400,
                    "message": "Required Parameters Not Passed",
                    "data": {}
                }
                json_data = json.dumps(data)
                return json.loads(json_data)
        except Exception as e:
            return json.dumps({'error': str(e)})


    @http.route(['/api/product_prices/read'], csrf=False, type="json", auth="public", methods=["GET"], cors="*")
    def get_product_list_with_price(self, **kwargs):
        try:
            post = request.httprequest.headers
            api_key = post.get("api_key")
            if api_key:
                user_id = request.env["res.users.apikeys"]._check_credentials(scope='rpc', key=api_key)
                if user_id:
                    product_ids = request.env['product.template'].sudo().search([])
                    product_list = []
                    for product in product_ids:
                        product_data = {
                            'name': product.name,
                            'product_id': product.id,
                            'default_code': product.default_code,
                            'type': product.type,
                            'h_id':product.h_id,
                            'list_price': product.list_price,
                            'standard_price': product.standard_price,
                        }
                        product_list.append(product_data)
                    dump = json.dumps({'data': product_list})
                    return json.loads(dump)
                else:
                    dump = json.dumps({'error': 'Access token invalid!'})
                    return json.loads(dump)
            else:
                data = {
                    "status": "False",
                    "statusCode": 400,
                    "message": "Required Parameters Not Passed",
                    "data": {}
                }
                json_data = json.dumps(data)
                return json.loads(json_data)
        except Exception as e:
            return json.dumps({'error': str(e)})


    @http.route(['/api/partners/read'], csrf=False, type="json", auth="public", methods=["GET"], cors="*")
    def get_customer_list(self, **kwargs):
        try:
            post = request.httprequest.headers
            api_key = post.get("api_key")
            if api_key:
                user_id = request.env["res.users.apikeys"]._check_credentials(scope='rpc', key=api_key)
                if user_id:
                    customer_count = request.env['res.partner'].sudo().search_count([])
                    customer_ids = request.env['res.partner'].sudo().search([])
                    customer_list = []
                    for customer in customer_ids:
                        customer_data = {
                            'name': customer.name,
                            'customer_id': customer.id,
                            'email': customer.email or '',
                            'phone': customer.phone or '',
                            'street': customer.street or '',
                            'city': customer.city or '',
                            'country': customer.country_id.name if customer.country_id else '',
                            'vat': customer.vat or '',
                        }
                        customer_list.append(customer_data)
                    dump = json.dumps({
                        'count': customer_count,
                        'data': customer_list
                    })
                    return json.loads(dump)
                else:
                    dump = json.dumps({'error': 'Access token invalid!'})
                    return json.loads(dump)
            else:
                data = {
                    "status": "False",
                    "statusCode": 400,
                    "message": "Required Parameters Not Passed",
                    "data": {}
                }
                json_data = json.dumps(data)
                return json.loads(json_data)
        except Exception as e:
            return json.dumps({'error': str(e)})


    @http.route(['/api/product_categories/read'], csrf=False, type="json", auth="public", methods=["GET"], cors="*")
    def get_category_list(self, **kwargs):
        try:
            post = request.httprequest.headers
            api_key = post.get("api_key")
            if api_key:
                user_id = request.env["res.users.apikeys"]._check_credentials(scope='rpc', key=api_key)
                if user_id:
                    category_ids = request.env['pos.category'].sudo().search([])
                    category_list = []
                    for category in category_ids:
                        category_data = {
                            'categoty_id': category.id,
                            'name': category.name,
                            'parent_category': category.parent_id.name if category.parent_id else '',
                            'display_name': category.display_name,
                        }
                        category_list.append(category_data)
                    dump = json.dumps({'data': category_list})
                    return json.loads(dump)
                else:
                    dump = json.dumps({'error': 'Access token invalid!'})
                    return json.loads(dump)
            else:
                data = {
                    "status": "False",
                    "statusCode": 400,
                    "message": "Required Parameters Not Passed",
                    "data": {}
                }
                json_data = json.dumps(data)
                return json.loads(json_data)
        except Exception as e:
            return json.dumps({'error': str(e)})

    @http.route(['/api/product_categories/create'], csrf=False, type="json", auth="public", methods=["POST"], cors="*")
    def set_category_details(self, **kwargs):
        try:
            post = request.httprequest.headers
            api_key = post.get("api_key")
            if api_key:
                parameters = json.loads(http.request.httprequest.data)
                user_id = request.env["res.users.apikeys"]._check_credentials(scope='rpc', key=api_key)
                if user_id:
                    if parameters.get('id') and parameters.get('name'):
                        category = request.env['pos.category'].sudo().search([('h_id','=',str(parameters.get('id')).strip())])
                        if not category:
                            values = {
                                'h_id' : parameters.get('id'),
                                'name': parameters.get('name'),
                            }
                            category = request.env['pos.category'].sudo().create(values)
                            category_data = {
                                'odoo_id': category.id,
                                'name': category.name,
                                'id': category.h_id,
                            }
                            response_data = {
                                "status": "True",
                                "statusCode": 200,
                                "data": category_data
                            }
                            return response_data
                        else:
                            dump = json.dumps({'error': 'Category Already Exist!'})
                            return json.loads(dump)
                    else:
                        dump = json.dumps({'error': 'Data invalid!'})
                        return json.loads(dump)
                else:
                    dump = json.dumps({'error': 'Access token invalid!'})
                    return json.loads(dump)
            else:
                data = {
                    "status": "False",
                    "statusCode": 400,
                    "message": "API key not found!",
                    "data": {}
                }
                json_data = json.dumps(data)
                return json.loads(json_data)
        except Exception as e:
            return json.dumps({'error': str(e)})

    @http.route('/api/partners/create', csrf=False, type="json", auth="public", methods=["POST"], cors="*")
    def create_partner(self, **kwargs):
        try:
            post = request.httprequest.headers
            api_key = post.get("api_key")
            parameters = json.loads(http.request.httprequest.data)
            if api_key:
                user_id = request.env["res.users.apikeys"]._check_credentials(scope='rpc', key=api_key)
                if user_id:
                    if parameters.get('id') and parameters.get('name') and parameters.get('email'):
                        partner_id = request.env['res.partner'].sudo().search([('h_id','=',parameters.get('id')),('email','=',parameters.get('email'))])
                        if not partner_id:
                            partner_vals = {
                                'name': parameters.get('name'),
                                'h_id' : parameters.get('id'),
                                "email": parameters.get('email'),
                            }
                            partner_id = request.env['res.partner'].sudo().create(partner_vals)
                            partner_data = {
                                "odoo_id": partner_id.id,
                                "name": partner_id.name,
                                "id": partner_id.h_id,
                                "email": partner_id.email,
                            }
                            response_data = {
                                "status": "True",
                                "statusCode": 200,
                                "data": partner_data
                            }
                            return response_data
                        else:
                            dump = json.dumps({'error': 'Customer Already Exist!'})
                            return json.loads(dump)
                    else:
                        dump = json.dumps({'error': 'Data invalid!'})
                        return json.loads(dump)
                else:
                    return {
                        "status": "False",
                        "message": "Access token invalid!",
                        "statusCode": 403,
                        "data": {}
                    }
            else:
                return {
                    "status": "False",
                    "message": "API key not found!",
                    "statusCode": 400,
                    "data": {}
                }
        except Exception as e:
            return {
                "status": "False",
                "message": str(e),
                "statusCode": 400,
                "data": {}
            }

    @http.route('/api/products/create', csrf=False, type="json", auth="public", methods=["POST"], cors="*")
    def create_product(self, **kwargs):
        try:
            post = request.httprequest.headers
            api_key = post.get("api_key")
            parameters = json.loads(http.request.httprequest.data)
            if api_key:
                user_id = request.env["res.users.apikeys"]._check_credentials(scope='rpc', key=api_key)
                if user_id:
                    product_id = request.env['product.template'].sudo().search([('h_id','=',parameters.get('id'))])
                    if not product_id:
                        product_vals = {
                            'name': parameters.get('name'),
                            'h_id' : parameters.get('id'),
                            "list_price": parameters.get('price'),
                            'invoice_policy': 'order',
                        }
                        product_id = request.env['product.template'].sudo().create(product_vals)
                        product_data = {
                            "odoo_id": product_id.id,
                            "name": product_id.name,
                            "id": product_id.h_id,
                            "price": product_id.list_price,
                            "invoice_policy": product_id.invoice_policy
                        }
                        response_data = {
                            "status": "True",
                            "statusCode": 200,
                            "data": product_data
                        }
                        return response_data
                    else:
                        dump = json.dumps({'error': 'Product Already Exist!'})
                        return json.loads(dump)
                else:
                    return {
                        "status": "False",
                        "message": "Access token invalid!",
                        "statusCode": 403,
                        "data": {}
                    }
            else:
                return {
                    "status": "False",
                    "message": "API key not found!",
                    "statusCode": 400,
                    "data": {}
                }
        except Exception as e:
            return {
                "status": "False",
                "message": str(e),
                "statusCode": 400,
                "data": {}
            }

    @http.route('/api/products/write', csrf=False, type="json", auth="public", methods=["POST"], cors="*")
    def write_product(self, **kwargs):
        print('API call started')
        try:
            post = request.httprequest.headers
            api_key = post.get("api_key")
            print('api_key:', api_key)
            parameters = json.loads(http.request.httprequest.data)
            if api_key:
                user_id = request.env["res.users.apikeys"]._check_credentials(scope='rpc', key=api_key)
                if user_id:
                    product_id = request.env['product.template'].sudo().search([('h_id', '=', parameters.get('id'))], limit=1)
                    if product_id:
                        product_id.sudo().write({
                            'name': parameters.get('name'),
                            'list_price': parameters.get('price'),
                        })
                        product_data = {
                            "odoo_id": product_id.id,
                            "name": product_id.name,
                            "id": product_id.h_id,
                            "price": product_id.list_price,
                        }
                        response_data = {
                            "status": "True",
                            "statusCode": 200,
                            "message": "Product Updated Successfully",
                            "data": product_data
                        }
                        return response_data
                    else:
                        dump = json.dumps({'error': 'Product Not Found!'})
                        return json.loads(dump)
                else:
                    return {
                        "status": "False",
                        "message": "Access token invalid!",
                        "statusCode": 403,
                        "data": {}
                    }
            else:
                return {
                    "status": "False",
                    "message": "API key not found!",
                    "statusCode": 400,
                    "data": {}
                }
        except Exception as e:
            return {
                "status": "False",
                "statusCode": 500,
                "message": str(e),
                "data": {}
            }


    @http.route('/api/partners/write', csrf=False, type="json", auth="public", methods=["POST"], cors="*")
    def write_partner(self, **kwargs):
        try:
            post = request.httprequest.headers
            api_key = post.get("api_key")
            print('api_key:', api_key)
            parameters = json.loads(http.request.httprequest.data)
            if api_key:
                user_id = request.env["res.users.apikeys"]._check_credentials(scope='rpc', key=api_key)
                if user_id:
                    partner_id = request.env['res.partner'].sudo().search([('h_id', '=', parameters.get('id'))], limit=1)
                    if partner_id:
                        partner_id.sudo().write({
                            'name': parameters.get('name'),
                            'email': parameters.get('email'),
                        })
                        partner_data = {
                            "odoo_id": partner_id.id,
                            "name": partner_id.name,
                            "id": partner_id.h_id,
                            "email": partner_id.email
                        }
                        response_data = {
                            "status": "True",
                            "statusCode": 200,
                            "message": "Customer Updated Successfully",
                            "data": partner_data
                        }
                        return response_data
                    else:
                        response_data = {
                            "status": "False",
                            "statusCode": 404,
                            "message": "Customer Not Found!",
                            "data": {}
                        }
                        return response_data
                else:
                    return {
                        "status": "False",
                        "message": "Access token invalid!",
                        "statusCode": 403,
                        "data": {}
                    }
            else:
                return {
                    "status": "False",
                    "message": "API key not found!",
                    "statusCode": 400,
                    "data": {}
                }
        except Exception as e:
            return {
                "status": "False",
                "statusCode": 500,
                "message": str(e),
                "data": {}
            }


    @http.route(['/api/product_categories/write'], csrf=False, type="json", auth="public", methods=["POST"], cors="*")
    def write_category_details(self, **kwargs):
        try:
            post = request.httprequest.headers
            api_key = post.get("api_key")
            parameters = json.loads(http.request.httprequest.data)
            if api_key:
                user_id = request.env["res.users.apikeys"]._check_credentials(scope='rpc', key=api_key)
                if user_id:
                    category = request.env['pos.category'].sudo().search([('h_id', '=', str(parameters.get('id')).strip())], limit=1)
                    if category:
                        category.sudo().write({
                            'name': parameters.get('name'),
                        })
                        category_data = {
                            'odoo_id': category.id,
                            'name': category.name,
                            'id': category.h_id,
                        }
                        response_data = {
                            "status": "True",
                            "statusCode": 200,
                            "message": "Category Updated Successfully",
                            "data": category_data
                        }
                        return response_data
                    else:
                        response_data = {
                            "status": "False",
                            "statusCode": 404,
                            "message": "Category Not Found",
                            "data": {}
                        }
                        return response_data
                else:
                    return {
                        "status": "False",
                        "message": "Access token invalid!",
                        "statusCode": 403,
                        "data": {}
                    }
            else:
                return {
                    "status": "False",
                    "message": "API key not found!",
                    "statusCode": 400,
                    "data": {}
                }
        except Exception as e:
            return {
                "status": "False",
                "statusCode": 500,
                "message": str(e),
                "data": {}
            }

    @http.route('/api/authentication', csrf=False, type="json", auth="public", methods=["POST"], cors="*")
    def api_key_check(self, **kwargs):
        api_key = http.request.httprequest.headers.get("api_key")
        try:
            if api_key:
                user_id = request.env["res.users.apikeys"]._check_credentials(key=api_key, scope='rpc')
                if user_id:
                    return {
                        "status": "True",
                        "statusCode": 200,
                        "data": "Valid API KEY"
                    }
                else:
                    return {
                        "status": "False",
                        "message": "Invalid API KEY",
                        "data": {}
                    }
        except Exception as e:
            return {
                "status": "False",
                "message": str(e),
                "statusCode": 400,
                "data": {}
            }

    @http.route('/api/create_credit_note', csrf=False, type="json",  auth="public", methods=["POST"], cors="*")
    def create_credit_note(self, **kwargs):
        try:
            post = request.httprequest.headers
            api_key = post.get("api_key")
            if api_key:
                user_id = request.env["res.users.apikeys"]._check_credentials(scope='rpc', key=api_key)
                if user_id:
                    data = json.loads(request.httprequest.data)
                    required_fields = ['date', 'h_id']
                    customer_data = json.loads(request.httprequest.data)
                    missing_fields = [field for field in required_fields if not customer_data.get(field)]
                    if missing_fields:
                        return {'status': 'error', 'message': f'Missing required fields: {", ".join(missing_fields)}'}
                    invoice = request.env['account.move'].sudo().search([('h_id', '=', data['h_id']), ('move_type', '=', 'out_invoice')], limit=1)
                    if not invoice:
                        return {'status': 'error', 'message': f"Invoice with H ID {data['order_id']} not found."}
                    credit_note_wizard = request.env['account.move.reversal'].sudo().create({
                        'move_ids': [(6, 0, [invoice.id])],
                        'reason': data.get('reason', 'Credit Note'),
                        'journal_id': invoice.journal_id.id,
                        'date': data['date'],
                    })
                    credit_note_wizard.reverse_moves()
                    credit_note = request.env['account.move'].sudo().search([('reversed_entry_id', '=', invoice.id)], limit=1)
                    line_ids_remove = set()
                    product_h_ids = []
                    if credit_note:
                        order_lines = data.pop('order_line', [])
                        if order_lines:
                            for line in order_lines:
                                product_h_ids.append(str(line.get('h_id')))
                                prod_line = credit_note.invoice_line_ids.filtered(lambda l: l.product_id.h_id == str(line.get('h_id')))
                                if prod_line:
                                    prod_line.write({'quantity': line.get('quantity') if line.get('quantity', False) else prod_line.quantity})
                            for line in order_lines:
                                if line and line.get('h_id', False) and line.get('quantity', False):
                                    line_ids = credit_note.invoice_line_ids.filtered(lambda l: l.product_id.h_id not in product_h_ids)
                                    if line_ids.ids:
                                        for lid in line_ids:
                                            line_ids_remove.add(lid.id)
                                else:
                                    line_ids = credit_note.invoice_line_ids.filtered(lambda l: l.product_id.h_id not in product_h_ids)
                                    if line_ids.ids:
                                        for lid in line_ids:
                                            line_ids_remove.add(lid.id)
                            if line_ids_remove:
                                for line_id in line_ids_remove:
                                    credit_note.write({'invoice_line_ids': [(3, line_id)]})
                        credit_note.action_post()
                        # make payment
                        wizard = request.env['account.payment.register'].with_context(active_model='account.move',active_ids=credit_note.ids).sudo().create({
                            'payment_date': invoice.date,
                        })
                        payment = wizard.sudo()._create_payments()
                    dump = json.dumps({'status': 'success', 'credit_note_id': credit_note.id})
                    return json.loads(dump)
                else:
                    dump = json.dumps({'error': str('Access token invalid !')})
                    return json.loads(dump)
            else:
                dump = json.dumps({'error': str('API key not found!')})
                return json.loads(dump)
        except Exception as e:
            return json.dumps({'status': 'error', 'message': str(e)})
