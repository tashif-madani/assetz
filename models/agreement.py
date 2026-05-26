from odoo import api, fields, models


class AssetzAgreement(models.Model):
    """Customer agreement — a contract under which orders are placed.

    Each agreement covers a date range for one customer. Orders attached
    to the agreement inherit the customer and surface their lines here
    so the back-office can see everything in one place.
    """

    _name = "assetz.agreement"
    _description = "Assetz Agreement"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_start desc, id desc"

    name = fields.Char(
        string="Agreement Name",
        required=True,
        tracking=True,
        default="New",
        copy=False,
    )
    customer_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
        tracking=True,
    )
    date_start = fields.Date(string="Start Date", required=True, tracking=True)
    date_end = fields.Date(string="End Date", required=True, tracking=True)
    total_days = fields.Integer(
        string="Total Days",
        compute="_compute_total_days",
        store=True,
    )
    state = fields.Selection(
        selection=[("valid", "Valid"), ("expired", "Expired")],
        string="Status",
        compute="_compute_state",
        store=True,
        tracking=True,
    )
    notes = fields.Text(string="Notes")

    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
    )

    order_ids = fields.One2many(
        "sale.order",
        "agreement_id",
        string="Orders",
        domain="[('is_assetz_order', '=', True)]",
    )
    order_count = fields.Integer(compute="_compute_line_counts")

    # Flattened lines coming through linked orders (sale.order.line records).
    order_line_ids = fields.One2many(
        "sale.order.line",
        compute="_compute_lines",
        string="Lines",
    )
    order_line_count = fields.Integer(compute="_compute_line_counts")

    @api.depends("date_start", "date_end")
    def _compute_total_days(self):
        for agr in self:
            if agr.date_start and agr.date_end:
                agr.total_days = (agr.date_end - agr.date_start).days
            else:
                agr.total_days = 0

    @api.depends("date_end")
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for agr in self:
            if agr.date_end and agr.date_end < today:
                agr.state = "expired"
            else:
                agr.state = "valid"

    @api.depends("order_ids", "order_ids.order_line")
    def _compute_lines(self):
        for agr in self:
            agr.order_line_ids = agr.order_ids.mapped("order_line")

    @api.depends("order_ids", "order_line_ids")
    def _compute_line_counts(self):
        for agr in self:
            agr.order_count = len(agr.order_ids)
            agr.order_line_count = len(agr.order_line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("assetz.agreement") or "New"
                )
        return super().create(vals_list)

    def action_view_orders(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Orders — {self.name}",
            "res_model": "sale.order",
            "view_mode": "list,form,kanban",
            "domain": [("agreement_id", "=", self.id)],
            "context": {
                "default_agreement_id": self.id,
                "default_partner_id": self.customer_id.id,
                "default_is_assetz_order": True,
            },
        }
