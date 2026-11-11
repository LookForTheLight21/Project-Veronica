// ========================================================
// Project Veronica: Tier 1 ESP32 Lectern Desk Pod 
// Application ID: VK26-AU-HCI-0072
// Features: 15-deg Ergonomic Wedge, LCD2004 Bezel, TTP229 Matrix,
//           Closed-Bottom Hotel CR80 Keycard Dock & Hidden PN532 Bay
// ========================================================

$fn = 60;

// Base Dimensions (mm)
pod_l    = 165.0;
pod_w    = 125.0;
front_h  = 22.0;
rear_h   = 48.0;
wall     = 3.0;

// Standard CR80 ID Card Slot Dimensions + Clearances (mm)
card_w   = 88.0;
card_thk = 4.0;

module veronica_desk_pod() {
    difference() {
        union() {
            // 1. OUTER ANGLED WEDGE HULL
            polyhedron(
                points = [
                    [-pod_l/2, -pod_w/2, 0],
                    [ pod_l/2, -pod_w/2, 0],
                    [ pod_l/2,  pod_w/2, 0],
                    [-pod_l/2,  pod_w/2, 0],
                    [-pod_l/2, -pod_w/2, front_h],
                    [ pod_l/2, -pod_w/2, front_h],
                    [ pod_l/2,  pod_w/2, rear_h],
                    [-pod_l/2,  pod_w/2, rear_h]
                ],
                faces = [
                    [0, 1, 2, 3], [4, 5, 1, 0], [7, 6, 5, 4],
                    [5, 6, 2, 1], [6, 7, 3, 2], [7, 4, 0, 3]
                ]
            );

            // 2. FRONT CARD RETENTION LIP (Solid, seamlessly joined with thumb scoop)
            translate([-18, -32.5, front_h + 6.0])
                rotate([-10.5, 0, 0])
                difference() {
                    cube([card_w + 6.0, 3.5, 16.0], center = true);
                    // Ergonomic thumb scoop
                    translate([0, 0, 6.0])
                        rotate([90, 0, 0])
                        cylinder(h = 10, d = 22.0, center = true);
                }
        }

        // 3. INNER ELECTRONICS CAVITY (Kept lower in front so it never punctures card pocket)
        polyhedron(
            points = [
                [-pod_l/2 + wall, -pod_w/2 + wall, wall],
                [ pod_l/2 - wall, -pod_w/2 + wall, wall],
                [ pod_l/2 - wall,  pod_w/2 - wall, wall],
                [-pod_l/2 + wall,  pod_w/2 - wall, wall],
                [-pod_l/2 + wall, -pod_w/2 + wall, front_h - wall - 8.0],
                [ pod_l/2 - wall, -pod_w/2 + wall, front_h - wall - 8.0],
                [ pod_l/2 - wall,  pod_w/2 - wall, rear_h - wall],
                [-pod_l/2 + wall,  pod_w/2 - wall, rear_h - wall]
            ],
            faces = [
                [0, 1, 2, 3], [4, 5, 1, 0], [7, 6, 5, 4],
                [5, 6, 2, 1], [6, 7, 3, 2], [7, 4, 0, 3]
            ]
        );

        // 4. LCD2004 DISPLAY BEZEL WINDOW (Top-Left)
        translate([-26, 20, front_h + 10])
            rotate([-10.5, 0, 0])
            cube([98.0, 41.0, 22.0], center = true);

        // 5. TTP229 CAPACITIVE TOUCH KEYPAD WINDOW (Top-Right)
        translate([52, 10, front_h + 10])
            rotate([-10.5, 0, 0])
            cube([42.0, 68.0, 22.0], center = true);

        // 6. CLOSED-BOTTOM CR80 DROP CHANNEL (Depth = 18mm, completely sealed base)
        translate([-18, -29.0, front_h + 4.0])
            rotate([-10.5, 0, 0])
            cube([card_w, card_thk, 18.0], center = true);

        // 7. HIDDEN INTERNAL PN532 SENSOR POCKET (1.2mm behind card slot)
        translate([-18, -24.8, front_h - 6.0])
            rotate([-10.5, 0, 0])
            cube([46.0, 6.0, 36.0], center = true);

        // 8. STATUS LED APERTURE & ACOUSTIC BUZZER PORTS
        for (dx = [-4, 4], dy = [-4, 4]) {
            translate([45 + dx, -30 + dy, front_h])
                cylinder(h = 18, d = 2.2, center = true);
        }

        // 9. SIDE/REAR USB-C 5V CHARGING PORT CUTOUT
        translate([pod_l/2, -15, 12])
            cube([wall * 4, 14.0, 7.5], center = true);
    }
}

veronica_desk_pod();
