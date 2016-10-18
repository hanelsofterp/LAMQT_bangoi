{
    'name': 'Purchase Receipt for other currency (real time exchange rate)',
	'summary': """Purchase Receipt for other currency with real time exchange rate 
					+ Allow to choose other currencies directly in the form
                    + Allow to key in real-time Exchange rate in the form
                    + When system post journal entries: Need to get Currency, Currency Amount and convert to base currency (using the Exchange Rate on Purchase Receipt)""",
    'version': '1.0',
    'category': 'Purchase',
    'description': """ 
                    Accounting > Purchase Receipts > Create new > Validate
                        + Allow to choose other currencies directly in the form
						+ Allow to key in real-time Exchange rate in the form
						+ When system post journal entries: Need to get Currency, Currency Amount and convert to base currency (using the Exchange Rate on Purchase Receipt)
                    """,
    'author': "HanelSoft",
    'website': 'http://www.hanelsoft.vn/',
    'depends': ['account_voucher'],
    'data': ['pr_other_currency.xml'],
    'installable': True,
    'auto_install': False,
    'application': False,
    'currency': 'EUR',
    'price': 211.0
}
