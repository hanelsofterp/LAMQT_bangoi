__author__ = 'LamQT' 

from openerp import api, fields, models
from openerp.tools.float_utils import float_compare, float_round
from openerp.tools.translate import _
from openerp.exceptions import except_orm

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
    def _voucher_move_line_create_new(self, line, voucher, move_id, company_currency, current_currency, tot_line):
        """ Create one move line per voucher line where amount is not 0.0 AND (second part of the clause)
            only if the original move line was not having debit = credit = 0 (which is a legal value)
        """
        prec = self.env['decimal.precision'].precision_get('Account')
        if not line.amount and not (line.move_line_id and not float_compare(
                line.move_line_id.debit, line.move_line_id.credit, precision_digits=prec
        ) and not float_compare(line.move_line_id.debit, 0.0, precision_digits=prec)):
            return tot_line, False
        ctx = self.env.context.copy()
        voucher_currency = voucher.journal_id.currency or voucher.company_id.currency_id
        ctx.update({
            'voucher_special_currency_rate': voucher_currency.rate * voucher.payment_rate,
            'voucher_special_currency':
                voucher.payment_rate_currency_id and voucher.payment_rate_currency_id.id or False})
        move_line_obj = self.env['account.move.line']
        currency_obj = self.env['res.currency']
        # Convert the amount set on the voucher line into the currency of the voucher's company
        # This calls res.currency.compute() with the right context, so that it will take either the rate
        # on the voucher if it is relevant or will use the default behaviour
        amount = self._convert_amount(line.untax_amount or line.amount, voucher.id)
        # If the amount encoded in voucher is equal to the amount unreconciled,
        # we need to compute the Currency rate difference
        if line.amount == line.amount_unreconciled:
            if not line.move_line_id:
                raise except_orm(_('Wrong voucher line'),
                                 _("The invoice you are willing to pay is not valid anymore."))
            sign = line.type == 'dr' and -1 or 1
            currency_rate_difference = sign * (line.move_line_id.amount_residual - amount)
        else:
            currency_rate_difference = 0.0
        move_line = self.with_context(**ctx)._prepare_voucher_account_move_line_vals(
            line, voucher, move_id, company_currency)

        if amount < 0:
            amount = -amount
            if line.type == 'dr':
                line.type = 'cr'
            else:
                line.type = 'dr'
        if line.type == 'dr':
            tot_line += amount
            move_line['debit'] = amount
        else:
            tot_line -= amount
            move_line['credit'] = amount
        # Compute the amount in foreign currency
        foreign_currency_diff = 0.0
        amount_currency = False
        if line.move_line_id:
            # We want to set it on the account move line as soon as the original line had a foreign currency
            if line.move_line_id.currency_id and line.move_line_id.currency_id.id != company_currency:
                # we compute the amount in that foreign currency.
                if line.move_line_id.currency_id.id == current_currency:
                    # if the voucher and the voucher line share the same currency, there is no computation to do
                    sign = (move_line['debit'] - move_line['credit']) < 0 and -1 or 1
                    amount_currency = sign * line.amount
                else:
                    # If the rate is specified on the voucher, it will be used thanks to the special
                    # keys in the context  otherwise we use the rates of the system
                    amount_currency = currency_obj.with_context(**ctx).compute(
                        company_currency,
                        line.move_line_id.currency_id.id,
                        move_line['debit'] - move_line['credit']
                    )
            if line.amount == line.amount_unreconciled:
                foreign_currency_diff = line.move_line_id.amount_residual_currency - abs(amount_currency)

        move_line['amount_currency'] = amount_currency
        voucher_line = move_line_obj.create(move_line)
        rec_ids = [voucher_line.id, line.move_line_id.id]

        if not voucher.company_id.currency_id.is_zero(currency_rate_difference):
            # Change difference entry in company currency
            exch_lines = self._get_exchange_lines(line, move_id, currency_rate_difference,
                                                  company_currency, current_currency)
            new_id = move_line_obj.create(exch_lines[0])
            move_line_obj.create(exch_lines[1])
            rec_ids.append(new_id.id)

        if line.move_line_id and line.move_line_id.currency_id and not line.move_line_id.currency_id.is_zero(
                foreign_currency_diff):
            move_line_foreign_currency = self._prepare_move_line_foreign_currency_vals(
                line, move_id, foreign_currency_diff)
            new_id = move_line_obj.create(move_line_foreign_currency)
            rec_ids.append(new_id.id)
        return tot_line, rec_ids

    @api.model
    def _voucher_move_line_create(self, line, voucher, move_id, company_currency, current_currency, tot_line):
        tot_line, rec_ids = self._voucher_move_line_create_new(line, voucher, move_id, company_currency, current_currency, tot_line)
        if company_currency != current_currency and voucher.type == 'purchase':
            data = {}
            if rec_ids and len(rec_ids) > 0 and rec_ids[0]:
                data['currency_id'] = current_currency
                data['amount_currency'] = line.amount
                self.env['account.move.line'].browse(rec_ids[0]).write(data)
        return tot_line, rec_ids
    
    @api.model
    def voucher_move_line_create(self, voucher_id, line_total, move_id, company_currency, current_currency):
        """
        Create one account move line, on the given account move, per voucher line where amount is not 0.0.
        It returns Tuple with tot_line what is total of difference between debit and credit and
        a list of lists with ids to be reconciled with this format (total_deb_cred,list_of_lists).

        :param voucher_id: Voucher id what we are working with
        :param line_total: Amount of the first line, which correspond to the amount we should totally split
            among all voucher lines.
        :param move_id: Account move wher those lines will be joined.
        :param company_currency: id of currency of the company to which the voucher belong
        :param current_currency: id of currency of the voucher
        :return: Tuple build as (remaining amount not allocated on voucher lines, list of account_move_line
            created in this method)
        :rtype: tuple(float, list of int)
        """
        tot_line = line_total
        rec_lst_ids = []

        date = self.browse(voucher_id).read(['date'])[0]['date']
        ctx = self.env.context.copy()
        ctx.update({'date': date})
        voucher = self.env['account.voucher'].browse(voucher_id)
        for line in voucher.line_ids:
            tot_line, rec_ids = self._voucher_move_line_create(
                line, voucher, move_id, company_currency, current_currency, tot_line)
            if not rec_ids:
                continue
            if line.move_line_id.id:
                rec_lst_ids.append(rec_ids)
        return tot_line, rec_lst_ids
    
