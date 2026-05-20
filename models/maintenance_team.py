from odoo import api, fields, models


class AssetzMaintenanceTeam(models.Model):
    """Maintenance team for grouping technicians."""

    _name = "assetz.maintenance.team"
    _description = "Maintenance Team"
    _inherit = ["mail.thread"]
    _order = "sequence, name"

    name = fields.Char(
        string="Team Name",
        required=True,
        tracking=True,
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(string="Sequence", default=10)
    color = fields.Integer(string="Color Index")

    # === Team Members ===
    member_ids = fields.Many2many(
        comodel_name="hr.employee",
        relation="maintenance_team_member_rel",
        column1="team_id",
        column2="employee_id",
        string="Team Members",
    )
    member_count = fields.Integer(
        string="Member Count",
        compute="_compute_member_count",
    )

    # === Team Leader ===
    leader_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Team Leader",
        tracking=True,
    )

    # === Contact Info ===
    email = fields.Char(string="Team Email")
    phone = fields.Char(string="Team Phone")

    # === Statistics ===
    order_ids = fields.One2many(
        comodel_name="assetz.maintenance.order",
        inverse_name="team_id",
        string="Maintenance Orders",
    )
    order_count = fields.Integer(
        string="Total Orders",
        compute="_compute_order_stats",
    )
    pending_order_count = fields.Integer(
        string="Pending Orders",
        compute="_compute_order_stats",
    )
    completed_order_count = fields.Integer(
        string="Completed Orders",
        compute="_compute_order_stats",
    )

    # === Company ===
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )

    # === Computed Methods ===

    @api.depends("member_ids")
    def _compute_member_count(self):
        """Count team members."""
        for team in self:
            team.member_count = len(team.member_ids)

    def _compute_order_stats(self):
        """Compute order statistics."""
        for team in self:
            orders = team.order_ids
            team.order_count = len(orders)
            team.pending_order_count = len(
                orders.filtered(lambda o: o.state not in ("completed", "cancelled"))
            )
            team.completed_order_count = len(
                orders.filtered(lambda o: o.state == "completed")
            )

    # === Action Methods ===

    def action_view_orders(self):
        """View team's maintenance orders."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"{self.name} - Orders",
            "res_model": "assetz.maintenance.order",
            "view_mode": "list,form,kanban",
            "domain": [("team_id", "=", self.id)],
            "context": {"default_team_id": self.id},
        }

    def action_view_pending_orders(self):
        """View team's pending orders."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"{self.name} - Pending Orders",
            "res_model": "assetz.maintenance.order",
            "view_mode": "list,form,kanban",
            "domain": [
                ("team_id", "=", self.id),
                ("state", "not in", ("completed", "cancelled")),
            ],
            "context": {"default_team_id": self.id},
        }

    def action_view_members(self):
        """View team members."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"{self.name} - Members",
            "res_model": "hr.employee",
            "view_mode": "list,form",
            "domain": [("id", "in", self.member_ids.ids)],
        }
