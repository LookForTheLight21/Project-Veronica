// ========================================================
// Project Veronica: Desk Pod Lectern Enclosure (v2.0)
// Application ID: VK26-AU-HCI-0072
// Track: HCI 2.0 Designing Interaction Beyond Chat
// Material Specification: PETG / Heat-Resistant ASA
// ========================================================

$fn = 80;

// Enclosure Base Parameters (mm)
pod_length = 140.0;
pod_width  = 105.0;
pod_height = 38.0;
wall_thick = 2.4;
tilt_angle = 15.0;

module enclosure_shell() {
    difference() {
        // Outer Solid Beveled Wedge
        cube([pod_length, pod_width, pod_height], center = true);

        // Inner Electronics Cavity (ESP32, PN532, Piezo)
        translate([0, 0, wall_thick])
            cube([pod_length - (2 * wall_thick), 
                  pod_width  - (2 * wall_thick), 
                  pod_height], center = true);

        // Top Recess Window: TTP229 Capacitive Touch Keypad (65x65mm)
        translate([0, 10, (pod_height / 2) - 2])
            cube([65.0, 65.0, 6.0], center = true);

        // Top Friction Pocket: NXP PN532 NFC Sensor Coil (<20mm read depth)
        translate([0, -32, (pod_height / 2) - 2.5])
            cube([45.0, 45.0, 4.0], center = true);

        // Rear Cutout: USB-C 5V Power Supply Port (12x6mm)
        translate([0, (pod_width / 2), -5])
            cube([12.0, wall_thick * 3, 6.0], center = true);

        // Acoustic Pinholes for 5V Piezo Buzzer Feedback (4x 2mm ports)
        translate([35, -30, pod_height / 2 - 3])
            cylinder(h = 10, d = 2.0, center = true);
        translate([38, -30, pod_height / 2 - 3])
            cylinder(h = 10, d = 2.0, center = true);
        translate([35, -33, pod_height / 2 - 3])
            cylinder(h = 10, d = 2.0, center = true);
        translate([38, -33, pod_height / 2 - 3])
            cylinder(h = 10, d = 2.0, center = true);
    }
}

// Render 3D Enclosure Solid
enclosure_shell();
