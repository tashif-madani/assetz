from odoo import api, fields, models

from .industry_examples import INDUSTRY_EXAMPLES


class AssetzLocation(models.Model):
    """Flexible location model with hierarchy support for asset tracking."""

    _name = "assetz.location"
    _description = "Asset Location"
    _parent_name = "parent_id"
    _parent_store = True
    _order = "sequence, complete_name"

    # Industry-specific example text (computed from settings)
    example_location_name = fields.Char(
        string="Example Location Name",
        compute="_compute_industry_examples",
        compute_sudo=True,
    )

    def _compute_industry_examples(self):
        """Compute industry-specific example text based on settings."""
        industry = self.env["ir.config_parameter"].sudo().get_param(
            "assetz.industry_preset", "custom"
        )
        examples = INDUSTRY_EXAMPLES.get(industry, INDUSTRY_EXAMPLES["custom"])
        for rec in self:
            rec.example_location_name = f"e.g. {examples.get('location_name', '')}"

    name = fields.Char(string="Location Name", required=True)
    code = fields.Char(
        string="Location Code",
        help="Short code for quick identification",
    )
    complete_name = fields.Char(
        string="Complete Name",
        compute="_compute_complete_name",
        recursive=True,
        store=True,
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(string="Sequence", default=10)
    color = fields.Integer(string="Color")

    # Hierarchy
    parent_id = fields.Many2one(
        comodel_name="assetz.location",
        string="Parent Location",
        index=True,
        ondelete="cascade",
    )
    parent_path = fields.Char(index=True, unaccent=False)
    child_ids = fields.One2many(
        comodel_name="assetz.location",
        inverse_name="parent_id",
        string="Sub Locations",
    )

    # Configurable location type
    location_type = fields.Selection(
        selection=[
            ("warehouse", "Warehouse/Building"),
            ("floor", "Floor/Level"),
            ("zone", "Zone/Area"),
            ("room", "Room"),
            ("rack", "Rack/Shelf"),
            ("bin", "Bin/Slot"),
            ("virtual", "Virtual Location"),
            ("external", "External/Client Site"),
            ("transit", "In Transit"),
        ],
        string="Location Type",
        default="room",
        help="Type of location for organizational purposes",
    )

    # Address information
    street = fields.Char(string="Street")
    street2 = fields.Char(string="Street 2")
    city = fields.Char(string="City")
    state_id = fields.Many2one(
        comodel_name="res.country.state",
        string="State",
    )
    country_id = fields.Many2one(
        comodel_name="res.country",
        string="Country",
    )
    zip_code = fields.Char(string="ZIP Code")

    # GPS coordinates
    gps_latitude = fields.Float(
        string="GPS Latitude",
        digits=(10, 7),
        help="GPS latitude coordinate",
    )
    gps_longitude = fields.Float(
        string="GPS Longitude",
        digits=(10, 7),
        help="GPS longitude coordinate",
    )

    # Contact and responsibility
    manager_id = fields.Many2one(
        comodel_name="res.users",
        string="Location Manager",
        help="Person responsible for this location",
    )
    contact_phone = fields.Char(string="Contact Phone")
    contact_email = fields.Char(string="Contact Email")

    # Multi-company support
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )

    # Capacity and usage
    capacity = fields.Integer(
        string="Capacity",
        help="Maximum number of assets this location can hold",
    )
    notes = fields.Text(string="Notes")

    # Statistics
    asset_count = fields.Integer(
        string="Asset Count",
        compute="_compute_asset_count",
    )

    _sql_constraints = [
        (
            "code_company_uniq",
            "unique(code, company_id)",
            "Location code must be unique per company!",
        ),
    ]

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        """Compute the full hierarchical name."""
        for location in self:
            if location.parent_id:
                location.complete_name = (
                    f"{location.parent_id.complete_name} / {location.name}"
                )
            else:
                location.complete_name = location.name

    def _compute_asset_count(self):
        """Compute the number of assets at this location."""
        asset_model = self.env["assetz.asset"]
        for location in self:
            location.asset_count = asset_model.search_count(
                [("location_id", "=", location.id)]
            )

    def action_view_assets(self):
        """Open assets view filtered by this location."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Assets - {self.name}",
            "res_model": "assetz.asset",
            "view_mode": "list,kanban,form",
            "views": [(False, "list"), (False, "kanban"), (False, "form")],
            "domain": [("location_id", "=", self.id)],
            "context": {"default_location_id": self.id},
        }

    def name_get(self):
        """Return complete name for locations."""
        return [(loc.id, loc.complete_name or loc.name) for loc in self]

    @api.constrains("parent_id")
    def _check_parent_id(self):
        """Prevent circular references in location hierarchy."""
        if not self._check_recursion():
            raise models.ValidationError(
                "Error! You cannot create recursive location hierarchy."
            )

    def get_full_address(self):
        """Return formatted full address."""
        self.ensure_one()
        parts = []
        if self.street:
            parts.append(self.street)
        if self.street2:
            parts.append(self.street2)
        if self.city:
            parts.append(self.city)
        if self.state_id:
            parts.append(self.state_id.name)
        if self.zip_code:
            parts.append(self.zip_code)
        if self.country_id:
            parts.append(self.country_id.name)
        return ", ".join(parts)


class AssetMovement(models.Model):
    """Track asset movements between locations."""

    _name = "assetz.asset.movement"
    _description = "Asset Movement"
    _order = "movement_date desc, id desc"
    _inherit = ["mail.thread"]

    name = fields.Char(
        string="Reference",
        default="New",
        readonly=True,
        copy=False,
    )
    asset_id = fields.Many2one(
        comodel_name="assetz.asset",
        string="Asset",
        required=True,
        ondelete="cascade",
        tracking=True,
    )
    asset_code = fields.Char(
        related="asset_id.code",
        string="Asset Code",
        store=True,
    )

    from_location_id = fields.Many2one(
        comodel_name="assetz.location",
        string="From Location",
        tracking=True,
    )
    to_location_id = fields.Many2one(
        comodel_name="assetz.location",
        string="To Location",
        tracking=True,
    )

    moved_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Moved By",
        default=lambda self: self.env.user,
        tracking=True,
    )
    movement_date = fields.Datetime(
        string="Movement Date",
        default=fields.Datetime.now,
        required=True,
        tracking=True,
    )

    movement_type = fields.Selection(
        selection=[
            ("transfer", "Location Transfer"),
            ("issue", "Issued to Recipient"),
            ("return", "Returned"),
            ("maintenance", "Sent for Maintenance"),
            ("disposal", "Disposed/Retired"),
            ("initial", "Initial Placement"),
            ("adjustment", "Inventory Adjustment"),
        ],
        string="Movement Type",
        required=True,
        default="transfer",
        tracking=True,
    )

    reason = fields.Text(
        string="Reason",
        help="Reason for the movement",
    )
    notes = fields.Text(string="Notes")

    # Related document reference
    reference_type = fields.Selection(
        selection=[
            ("manual", "Manual"),
            ("issue_order", "Issue Order"),
            ("maintenance", "Maintenance Request"),
            ("disposal", "Disposal Order"),
        ],
        string="Reference Type",
        default="manual",
    )
    reference_id = fields.Integer(
        string="Reference ID",
        help="ID of the related document",
    )

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Generate movement reference on creation."""
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "assetz.asset.movement"
                ) or "New"
        return super().create(vals_list)
