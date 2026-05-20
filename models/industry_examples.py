from odoo import api, models

# Industry-specific examples for placeholder text and help
INDUSTRY_EXAMPLES = {
    "it": {
        "asset_name": "Dell Laptop XPS 15, HP Monitor 27-inch",
        "category_name": "IT Equipment, Computers, Peripherals",
        "code_prefix": "LAP, MON, SRV",
        "attribute_name": "RAM Size, Processor, Storage",
        "attribute_options": "8GB, 16GB, 32GB",
        "location_name": "Server Room, IT Office, Floor 2",
        "serial_prefix": "IT",
    },
    "manufacturing": {
        "asset_name": "Forklift Unit A1, CNC Machine #5, Welding Station 3",
        "category_name": "Heavy Machinery, Production Equipment, Safety Gear",
        "code_prefix": "FLT, CNC, WLD",
        "attribute_name": "Engine Capacity, Load Limit, Operating Hours",
        "attribute_options": "Small, Medium, Large, Heavy-Duty",
        "location_name": "Warehouse A, Plant Floor 2, Assembly Line 1",
        "serial_prefix": "MFG",
    },
    "healthcare": {
        "asset_name": "MRI Scanner Unit 1, Patient Monitor, Ultrasound Machine",
        "category_name": "Medical Equipment, Diagnostic Devices, Patient Care",
        "code_prefix": "MRI, ECG, USG",
        "attribute_name": "Calibration Date, Certification Level, Power Rating",
        "attribute_options": "Class I, Class II, Class III",
        "location_name": "Radiology Dept, ICU, Emergency Ward",
        "serial_prefix": "MED",
    },
    "realestate": {
        "asset_name": "HVAC Unit Building A, Conference Table Room 101",
        "category_name": "HVAC Systems, Furniture, Fixtures",
        "code_prefix": "HVC, FRN, FXT",
        "attribute_name": "Capacity, Material, Warranty Period",
        "attribute_options": "Wood, Metal, Glass, Fabric",
        "location_name": "Building A, Floor 3, Conference Room 1",
        "serial_prefix": "FAC",
    },
    "fleet": {
        "asset_name": "Delivery Truck #12, Company Car - Sedan",
        "category_name": "Trucks, Cars, Motorcycles",
        "code_prefix": "TRK, CAR, BKE",
        "attribute_name": "Engine Size, Fuel Type, Mileage",
        "attribute_options": "Diesel, Petrol, Electric, Hybrid",
        "location_name": "Main Garage, Depot A, Service Center",
        "serial_prefix": "VEH",
    },
    "custom": {
        "asset_name": "Asset Name",
        "category_name": "Category Name",
        "code_prefix": "CAT",
        "attribute_name": "Attribute Name",
        "attribute_options": "Option 1, Option 2, Option 3",
        "location_name": "Location Name",
        "serial_prefix": "AST",
    },
}


class IndustryExamplesMixin(models.AbstractModel):
    """Mixin to provide industry-specific examples based on settings."""

    _name = "assetz.industry.examples.mixin"
    _description = "Industry Examples Mixin"

    @api.model
    def get_industry_preset(self):
        """Get the current industry preset from settings."""
        return self.env["ir.config_parameter"].sudo().get_param(
            "assetz.industry_preset", "custom"
        )

    @api.model
    def get_industry_examples(self, example_type=None):
        """Get industry-specific examples.

        Args:
            example_type: The type of example to get (e.g., 'asset_name', 'category_name')
                         If None, returns all examples for the current industry.

        Returns:
            str or dict: The example string or dict of all examples.
        """
        industry = self.get_industry_preset()
        examples = INDUSTRY_EXAMPLES.get(industry, INDUSTRY_EXAMPLES["custom"])

        if example_type:
            return examples.get(example_type, "")
        return examples

    @api.model
    def get_example_text(self, example_type):
        """Get formatted example text for display in forms.

        Args:
            example_type: The type of example (e.g., 'asset_name')

        Returns:
            str: Formatted example text like "e.g. Example 1, Example 2"
        """
        example = self.get_industry_examples(example_type)
        if example:
            return f"e.g. {example}"
        return ""
