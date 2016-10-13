__author__ = 'LamQT' 

from openerp import api, fields, models
from openerp.tools.float_utils import float_compare, float_round
from openerp.tools.translate import _


class npp_account_voucher(models.Model):
    _inherit = 'account.voucher'
    
    @api.model
    def _get_default_rate_pr(self):
        return self.currency_id and self.currency_id.rate_silent or 1
    
    @api.onchange('payment_rate_currency_id')
    def onchange_type(self):
        self.rate_pr = self.payment_rate_currency_id and self.payment_rate_currency_id.rate_silent or 1

    @api.multi
    def _paid_amount_in_company_currency(self):
        ctx = self.env.context.copy()
        for v in self:
            ctx.update({'date': v.date})
            # make a new call to browse in order to have the right date in the context, to get the right currency rate
            voucher = v
            ctx.update({
              'voucher_special_currency': voucher.payment_rate_currency_id and voucher.payment_rate_currency_id.id or False,
              'voucher_special_currency_rate': voucher.currency_id.rate * voucher.payment_rate, })
            if voucher.rate_pr == 1.0 or float_compare(voucher.currency_id.rate, voucher.rate_pr, precision_digits=6) == 0:
                voucher.paid_amount_in_company_currency = self.pool.get('res.currency').compute(self.env.cr, self.env.uid, voucher.currency_id.id, voucher.company_id.currency_id.id, voucher.amount, context=ctx)
            else:
                total = 0.0
                for line in voucher.line_dr_ids:
                    total += float_round(line.amount/voucher.rate_pr, 2)
                voucher.paid_amount_in_company_currency = total
    
    rate_pr = fields.Float(string='Current Rate', digits=(12, 6), default=_get_default_rate_pr)
    paid_amount_in_company_currency = fields.Float(compute=_paid_amount_in_company_currency, string='Paid Amount in Company Currency', readonly=True)
    
    @api.model
    def _prepare_voucher_account_move_line_vals(self, line, voucher, move_id, company_currency):
        move_line = {
            'journal_id': voucher.journal_id.id,
            'period_id': voucher.period_id.id,
            'name': line.name or '/',
            'account_id': line.account_id.id,
            'move_id': move_id,
            'partner_id': voucher.partner_id.id,
            'currency_id': line.move_line_id and (
                company_currency != line.move_line_id.currency_id.id and line.move_line_id.currency_id.id) or False,
            'analytic_account_id': line.account_analytic_id and line.account_analytic_id.id or False,
            'quantity': 1,
            'credit': 0.0,
            'debit': 0.0,
            'date': voucher.date
        }

        if voucher.tax_id and voucher.type in ('sale', 'purchase'):
            move_line.update({
                'account_tax_id': voucher.tax_id.id,
            })
        # Update name for this account.move.line to know what payment for
        move_line.update({'name': 'Payment for ' + str(line.move_line_id.invoice.number)})
        return move_line
    
    @api.multi
    def onchange_price_pr(self, line_ids, tax_id, partner_id=False, context=None):
        tax_pool = self.pool.get('account.tax')
        partner_pool = self.pool.get('res.partner')
        position_pool = self.pool.get('account.fiscal.position')
        journal_obj = context.get('journal_id', False)
        if not line_ids:
            line_ids = []
        res = {
            'tax_amount': False,
            'amount': False,
            'currency_id': False,
        }
        voucher_total = 0.0
        line_ids = context.get('line_dr_ids', False)
        if not line_ids:
            return True
        total_tax = 0.0
        for line in line_ids:
            line_amount = 0.0
            if line[0] == 0:
                line_amount = line[2]['amount']
            if line[0] == 1:
                if 'amount' in line[2]:
                    line_amount = line[2]['amount']
                else:
                    line_amount = self.env['account.voucher.line'].browse(line[1]).amount
            if line[0] == 2:
                continue
            if line[0] == 4:
                line_amount = self.env['account.voucher.line'].browse(line[1]).amount
            
            if tax_id:
                tax = [tax_pool.browse(self.env.cr, self.env.uid, tax_id, context=self.env.context)]
                if partner_id:
                    partner = partner_pool.browse(self.env.cr, self.env.uid, partner_id, context=self.env.context) or False
                    taxes = position_pool.map_tax(self.env.cr, self.env.uid, partner and partner.property_account_position or False, tax)
                    tax = tax_pool.browse(self.env.cr, self.env.uid, taxes, context=self.env.context)
                if not tax[0].price_include:
                    for tax_line in tax_pool.compute_all(self.env.cr, self.env.uid, tax, line_amount, 1).get('taxes', []):
                        total_tax += tax_line.get('amount')
            voucher_total += line_amount
        total = voucher_total + total_tax
        self.write(({'tax_amount': total_tax}))
        currency_id = False
        if journal_obj:
            journal_id_obj = self.env['account.journal'].browse(journal_obj)
            currency_id = journal_id_obj.currency.id or journal_id_obj.company_id.currency_id.id
        elif self.journal_id and self.journal_id.id:
            currency_id = self.journal_id and self.journal_id.currency.id or self.journal_id.company_id.currency_id.id
        res.update({
            'amount': total or voucher_total,
            'tax_amount': total_tax,
            'currency_id': currency_id,
        })
        return {
            'value': res
        }
        
    @api.model
    def _convert_amount(self, amount, voucher_id):
        '''
        This function convert the amount given in company currency. It takes either the rate in the voucher (if the
        payment_rate_currency_id is relevant) either the rate encoded in the system.

        :param amount: float. The amount to convert
        :param voucher: id of the voucher on which we want the conversion
        :param context: to context to use for the conversion. It may contain the key 'date' set to the voucher date
            field in order to select the good rate to use.
        :return: the amount in the currency of the voucher's company
        :rtype: float
        '''
        currency_obj = self.pool.get('res.currency')
        voucher = self.browse(voucher_id)
        if voucher.rate_pr == 1.0 or float_compare(voucher.currency_id.rate, voucher.rate_pr, precision_digits=6) == 0:
            return currency_obj.compute(self.env.cr, self.env.uid, voucher.currency_id.id, voucher.company_id.currency_id.id, amount, context=self.env.context)
        else:
            return float_round(amount/voucher.rate_pr, 2)
        
    @api.multi
    def onchange_journal(self, journal_id, line_ids, tax_id, partner_id, date, amount, ttype, company_id, context=None):
        res = super(npp_account_voucher, self).onchange_journal(journal_id, line_ids, tax_id, partner_id, date, amount, ttype, company_id, context=None)
        if context.get('pur_rec', False) == 'purchase_receipt' and tax_id and line_ids != [(6, 0, [])]:
            res['value'].update({'tax_id': tax_id})
            tax_pool = self.pool.get('account.tax')
            partner_pool = self.pool.get('res.partner')
            position_pool = self.pool.get('account.fiscal.position')
            voucher_total = 0.0
            total_tax = 0.0
            line_amount = 0.0
            for line in line_ids:
                if line[0] == 0:
                    line_amount += line[2]['amount']
                if line[0] == 1:
                    if 'amount' in line[2]:
                        line_amount += line[2]['amount']
                    else:
                        line_amount += self.env['account.voucher.line'].browse(line[1]).amount
                if line[0] == 2:
                    continue
                if line[0] == 4:
                    line_amount += self.env['account.voucher.line'].browse(line[1]).amount
                if line[0] == 6:
                    for n in line[2]:
                        line_amount += self.env['account.voucher.line'].browse(n).amount
            if tax_id:
                tax = [tax_pool.browse(self.env.cr, self.env.uid, tax_id, context=self.env.context)]
                if partner_id:
                    partner = partner_pool.browse(self.env.cr, self.env.uid, partner_id, context=self.env.context) or False
                    taxes = position_pool.map_tax(self.env.cr, self.env.uid, partner and partner.property_account_position or False, tax)
                    tax = tax_pool.browse(self.env.cr, self.env.uid, taxes, context=self.env.context)
                if not tax[0].price_include:
                    for tax_line in tax_pool.compute_all(self.env.cr, self.env.uid, tax, line_amount, 1).get('taxes', []):
                        total_tax += tax_line.get('amount')
            voucher_total = line_amount
            total = voucher_total + total_tax
            res['value'].update({
                                'amount': total or voucher_total,
                                'tax_amount': total_tax,
                                })
        return res
        
    @api.model
    def _voucher_move_line_create(self, line, voucher, move_id, company_currency, current_currency, tot_line):
        tot_line, rec_ids = super(npp_account_voucher, self)._voucher_move_line_create(line, voucher, move_id, company_currency, current_currency, tot_line)
        if company_currency != current_currency and voucher.type == 'purchase':
            data = {}
            if rec_ids and len(rec_ids) > 0 and rec_ids[0]:
                data['currency_id'] = current_currency
                data['amount_currency'] = line.amount
                self.env['account.move.line'].browse(rec_ids[0]).write(data)
        return tot_line, rec_ids
