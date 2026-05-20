from odoo import api, fields, models
from odoo.exceptions import UserError


class AssetzCreateChecklistWizard(models.TransientModel):
    """Wizard for selecting and applying a checklist template to a maintenance order."""

    _name = "assetz.create.checklist.wizard"
    _description = "Create Checklist Wizard"

    order_id = fields.Many2one(
        comodel_name="assetz.maintenance.order",
        string="Maintenance Order",
        required=True,
    )
    asset_id = fields.Many2one(
        comodel_name="assetz.asset",
        string="Asset",
        related="order_id.asset_id",
    )
    category_id = fields.Many2one(
        comodel_name="assetz.category",
        string="Asset Category",
        related="order_id.category_id",
    )
    maintenance_type = fields.Selection(
        related="order_id.maintenance_type",
        string="Maintenance Type",
    )

    template_id = fields.Many2one(
        comodel_name="assetz.checklist.template",
        string="Checklist Template",
        required=True,
        domain="['|', ('category_ids', '=', False), ('category_ids', 'in', category_id)]",
    )

    # Preview fields
    template_description = fields.Text(
        related="template_id.description",
        string="Description",
    )
    template_line_count = fields.Integer(
        related="template_id.line_count",
        string="Number of Items",
    )
    template_estimated_duration = fields.Float(
        related="template_id.estimated_duration",
        string="Est. Duration",
    )
    template_instructions = fields.Html(
        related="template_id.instructions",
        string="Instructions",
    )
    template_safety_notes = fields.Text(
        related="template_id.safety_notes",
        string="Safety Notes",
    )

    # Preview of template lines
    preview_line_ids = fields.One2many(
        related="template_id.line_ids",
        string="Checklist Items Preview",
    )

    replace_existing = fields.Boolean(
        string="Replace Existing Checklist",
        default=True,
        help="If checked, existing checklist items will be replaced. Otherwise, items will be added.",
    )

    def action_apply_template(self):
        """Apply the selected template to the maintenance order."""
        self.ensure_one()

        if not self.template_id:
            raise UserError("Please select a checklist template.")

        order = self.order_id

        # Clear existing checklist lines if replacing
        if self.replace_existing:
            order.checklist_line_ids.unlink()

        # Set the template on the order
        order.checklist_template_id = self.template_id.id

        # Create new lines from template
        for template_line in self.template_id.line_ids:
            self.env["assetz.maintenance.checklist.line"].create(
                {
                    "order_id": order.id,
                    "sequence": template_line.sequence,
                    "name": template_line.name,
                    "description": template_line.description,
                    "check_type": template_line.check_type,
                    "group_name": template_line.group_name,
                    "expected_min": template_line.expected_min,
                    "expected_max": template_line.expected_max,
                    "unit": template_line.unit,
                    "selection_options": template_line.selection_options,
                    "is_required": template_line.is_required,
                    "requires_photo": template_line.requires_photo,
                    "requires_notes": template_line.requires_notes,
                }
            )

        return {"type": "ir.actions.act_window_close"}
