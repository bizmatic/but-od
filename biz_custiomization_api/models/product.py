# -*- coding: utf-8 -*-

from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    h_id = fields.Char(string="H ID")

    def _update_price_from_bom(self):
        for product in self.search([]):
            product.button_bom_cost()

class ResPartner(models.Model):
    _inherit = 'res.partner'

    h_id = fields.Char(string="H ID")

class ResPartner(models.Model):
    _inherit = 'pos.category'

    h_id = fields.Char(string="H ID")

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    h_id = fields.Char(string="H ID")

class AccountMove(models.Model):
    _inherit = 'account.move'

    h_id = fields.Char(string="H ID")