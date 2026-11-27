// ============================================================================
// PROJECT VERONICA — NEW BUILD: DETACHABLE WALL DISPLAY & BEHIND-SCREEN POD
// Replaces Legacy Keypad + 16x2/20x4 Wedge Pod
// Features:
//   1. Wall-Mounted Vertical Height Adjustment Track (120mm travel, 9 detents)
//   2. Single-Axis Tilt Clevis Hinge (-15 deg to +45 deg, zero swivel)
//   3. Quick-Release Dovetail Wedge Dock (lift frame straight off wall stand)
//   4. 800x480 Touchscreen Front Bezel + Integrated Rear Circuit Enclosure
//   5. Behind-Screen Upper-Center PN532 NFC Cradle + Ferrite Shield Recess
//      for Tap-on-Screen Badge Authentication
//   6. NodeMCU ESP-32S (38-Pin) Bay + Piezo Buzzer Acoustic Grille
//
// NOTE: Pi 5 Ceiling Enclosure (Raspberry_pi_5._encloure.stl) is UNCHANGED.
// Units: millimeters (mm)
// ============================================================================

$fn = 48;

// ----------------------------------------------------------------------------
// PARAMETRIC DISPLAY DIMENSIONS (Adjust here for your exact 800x480 screen)
// Default: Standard 7-inch 800x480 HDMI/DSI Touch Monitor
//   (For 5-inch 800x480 screen, set screen_pcb_w=122, screen_pcb_h=77,
//    active_w=109, active_h=65, frame_w=148, frame_h=106)
// ----------------------------------------------------------------------------
active_w        = 155.0;   // Visible touchscreen glass width
active_h        = 87.0;    // Visible touchscreen glass height
screen_pcb_w    = 167.0;   // Inner display PCB/chassis pocket width
screen_pcb_h    = 102.0;   // Inner display PCB/chassis pocket height
screen_depth    = 9.0;     // Thickness of display panel

frame_w         = 190.0;   // Outer front/rear enclosure width
frame_h         = 126.0;   // Outer front/rear enclosure height
rear_cavity_d   = 28.0;    // Depth behind screen for ESP32, PN532 & Buzzer
wall_t          = 3.0;     // Enclosure structural wall thickness
fit_tol         = 0.4;     // 3D-printer sliding clearance per side

// Assembly Preview Mode:
//   "assembled" = Full assembled view on wall stand
//   "exploded"  = Exploded 5-part view
//   "part1" .. "part5" = Individual printable STL export
view_mode       = "assembled";
tilt_angle_deg  = 15;      // Preview screen upward tilt (-15 to +45 deg)
height_offset_z = 0;       // Preview height shift (-60 to +60 mm)

// Derived pivot origin
z_pivot = 110.0;
y_pivot = 92.0;

// ============================================================================
// PART 1: WALL ANCHOR & VERTICAL HEIGHT RAIL (part1_wall_rail_mount.stl)
// ============================================================================
module wall_rail_mount() {
    difference() {
        union() {
            // Back anchor plate centered in X: [-38..38], Y: [0..7], Z: [0..220]
            translate([-38, 0, 0])
                cube([76, 7, 220]);

            // T-Slot Neck: X: [-12..12], Y: [7..15], Z: [20..200]
            translate([-12, 7, 20])
                cube([24, 8, 180]);

            // T-Slot Wide Head: X: [-19..19], Y: [15..23], Z: [24..196]
            translate([-19, 15, 24])
                cube([38, 8, 172]);

            // Top & Bottom Safety End Stops (prevent carriage drop)
            translate([-24, 7, 0])
                cube([48, 20, 24]);
            translate([-24, 7, 196])
                cube([48, 20, 24]);
        }

        // 4x Wall Anchor Screw Holes (M5 + Countersink)
        for (sx = [-27, 27], sz = [14, 206]) {
            translate([sx, -1, sz])
                rotate([-90, 0, 0]) {
                    cylinder(h = 10, d = 5.5);
                    translate([0, 0, 4.5])
                        cylinder(h = 4.5, d1 = 5.5, d2 = 10.5);
                }
        }

        // 9x Indexed Height Lock Detent Notches (Right side of T-Head, every 15mm)
        // Travel range: Z = 50mm to 170mm (120mm net vertical height adjustment)
        for (kz = [50 : 15 : 170]) {
            translate([13, 19, kz])
                rotate([0, 90, 0])
                cylinder(h = 8, d = 5.4);
        }
    }
}

// ============================================================================
// PART 2: HEIGHT SLIDER CARRIAGE & SINGLE-AXIS TILT CLEVIS ARM
// ============================================================================
module height_tilt_arm() {
    difference() {
        union() {
            // 1. Height Carriage Collar around T-Track
            translate([-26, 4, z_pivot - 26])
                cube([54, 26, 52]);

            // 2. Side M5 Height-Lock Knob Boss (+X side)
            translate([28, 19, z_pivot])
                rotate([0, 90, 0])
                cylinder(h = 8, d = 16);

            // 3. Cantilever Standoff Arm (Projects out from Y=30 to Y=76)
            translate([-15, 30, z_pivot - 14])
                cube([30, 46, 28]);

            // 4. Dual Tilt Clevis Fork Ears (X = [-22..-13] and [13..22])
            for (ex = [-22, 13]) {
                translate([ex, 70, z_pivot - 24])
                    cube([9, 24, 48]);
                translate([ex, y_pivot, z_pivot])
                    rotate([0, 90, 0])
                    cylinder(h = 9, r = 24);
            }
        }

        // Carve Wall Plate Clearance (keeps back of collar at Y >= 8)
        translate([-30, 0, z_pivot - 28])
            cube([60, 8.0, 56]);

        // Carve T-Track Neck Sliding Channel (24 + 2*tol = 24.8mm)
        translate([-12 - fit_tol, 7, z_pivot - 28])
            cube([24 + 2*fit_tol, 8.4, 56]);

        // Carve T-Track Head Sliding Channel (38 + 2*tol = 38.8mm)
        translate([-19 - fit_tol, 15 - fit_tol, z_pivot - 28])
            cube([38 + 2*fit_tol, 8 + 2*fit_tol, 56]);

        // M5 Height-Lock Thumbscrew Bore + Captured Hex Nut Trap
        translate([15, 19, z_pivot])
            rotate([0, 90, 0])
            cylinder(h = 24, d = 5.4);
        translate([27, 19, z_pivot])
            rotate([0, 90, 0])
            cylinder(h = 4.5, d = 9.4, $fn = 6);

        // Internal Arm Cable Pass-Through Tunnel
        translate([-8, 34, z_pivot - 7])
            cube([16, 40, 14]);

        // Main M5 Tilt Pivot Axle Hole across Both Clevis Ears
        translate([-25, y_pivot, z_pivot])
            rotate([0, 90, 0])
            cylinder(h = 50, d = 5.4);

        // Curved Pitch Tilt Lock Arc Slot (-15 deg to +45 deg at R=16mm)
        // Note: positive +X rotation tilts front (+Y) UP, swinging rear (-16,0) DOWN (-sin(a))
        for (a = [-15 : 3 : 45]) {
            translate([-25, y_pivot - 16 * cos(a), z_pivot - 16 * sin(a)])
                rotate([0, 90, 0])
                cylinder(h = 50, d = 4.5);
        }
    }
}

// ============================================================================
// PART 3: QUICK-RELEASE DETACHABLE WEDGE & TILT TONGUE
// ============================================================================
module quick_release_wedge() {
    difference() {
        union() {
            // 1. Tilt Tongue fitting inside Part 2 Clevis (X = [-12.6..+12.6])
            translate([-13 + fit_tol, y_pivot, z_pivot])
                rotate([0, 90, 0])
                cylinder(h = 26 - 2*fit_tol, r = 21);
            translate([-13 + fit_tol, y_pivot, z_pivot - 21])
                cube([26 - 2*fit_tol, 17, 42]);

            // 2. Male Tapered Dovetail Quick-Release Wedge (Y = 108..119, Z = 84..136)
            // Flared wider at front (+Y) so frame drops down cleanly and cannot pull forward!
            hull() {
                translate([-21, 108, z_pivot - 26]) cube([42, 1, 52]);
                translate([-25, 117, z_pivot - 26]) cube([50, 2, 52]);
            }
        }

        // Main M5 Pivot Bore
        translate([-15, y_pivot, z_pivot])
            rotate([0, 90, 0])
            cylinder(h = 30, d = 5.4);

        // M4 Tilt Lock Screw Bore at R=16mm behind pivot
        translate([-15, y_pivot - 16, z_pivot])
            rotate([0, 90, 0])
            cylinder(h = 30, d = 4.4);

        // Vertical M4 Captive Lock Bore into Top Face of Wedge (X=0, Y=113.5, Z=136 down 14mm)
        translate([0, 113.5, z_pivot + 12])
            cylinder(h = 15, d = 4.0);
    }
}

// ============================================================================
// PART 4: FRONT DISPLAY BEZEL FRAME (800x480 TOUCH MONITOR)
// ============================================================================
module display_front_bezel() {
    y_back = 149.0;
    difference() {
        // Outer Front Frame Shell
        translate([-frame_w/2, y_back, z_pivot - frame_h/2])
            cube([frame_w, screen_depth + 3.0, frame_h]);

        // Display PCB Rear Pocket
        translate([-screen_pcb_w/2, y_back - 1, z_pivot - screen_pcb_h/2])
            cube([screen_pcb_w, screen_depth + 1.0, screen_pcb_h]);

        // Active Front Screen Aperture
        translate([-active_w/2, y_back + screen_depth - 1, z_pivot - active_h/2])
            cube([active_w, 5.0, active_h]);

        // 4x M3 Corner Assembly Screw Holes (inside 11.5mm border ribs)
        for (sx = [-frame_w/2 + 6, frame_w/2 - 6], sz = [z_pivot - frame_h/2 + 6, z_pivot + frame_h/2 - 6]) {
            translate([sx, y_back - 1, sz])
                rotate([-90, 0, 0])
                cylinder(h = 8.0, d = 3.2);
        }
    }
}

// ============================================================================
// PART 5: REAR BEHIND-SCREEN CIRCUIT HOUSING + QUICK-RELEASE DOCK
// Houses: PN532 NFC (Upper-Center Behind Glass + Ferrite Bay),
//         NodeMCU ESP-32S (Left), Piezo Buzzer (Bottom-Right)
// ============================================================================
module rear_circuit_housing() {
    y_wall_out = 118.0;
    y_wall_in  = y_wall_out + wall_t;         // 121.0mm
    y_front    = y_wall_in + rear_cavity_d;   // 149.0mm (mates with Front Bezel)

    union() {
        // 1. Hollowed Outer Shell + Quick-Release Female Receiver
        difference() {
            union() {
                // Main Rear Circuit Enclosure Block
                translate([-frame_w/2, y_wall_out, z_pivot - frame_h/2])
                    cube([frame_w, wall_t + rear_cavity_d, frame_h]);

                // Female Quick-Release Dovetail Receiver (Back Center: Y=106..118, Z=82..148)
                translate([-33, 106.5, z_pivot - 28])
                    cube([66, 11.5, 66]);
            }

            // A. Hollow Main Electronics Cavity (leaves 10mm corner screw ribs!)
            translate([-frame_w/2 + wall_t, y_wall_in, z_pivot - frame_h/2 + wall_t])
                cube([frame_w - 2*wall_t, rear_cavity_d + 2, frame_h - 2*wall_t]);

            // B. Carve Quick-Release Female Dovetail Pocket (Open at Bottom ONLY, roof stop Z=136.5)
            hull() {
                translate([-21 - fit_tol, 105, z_pivot - 30])
                    cube([42 + 2*fit_tol, 3, 56.5]);
                translate([-25 - fit_tol, 117 - fit_tol, z_pivot - 30])
                    cube([50 + 2*fit_tol, 2, 56.5]);
            }

            // C. Vertical M4 Locking Screw Hole through Receiver Roof (Z = 136..149)
            translate([0, 113.5, z_pivot + 25])
                cylinder(h = 15, d = 4.4);

            // D. Micro-USB Power Port for ESP32 (Bottom-Left Wall)
            translate([-61, y_wall_in + 4, z_pivot - frame_h/2 - 1])
                cube([14, 9, wall_t + 4]);

            // E. HDMI + USB-Touch Trunk Cable Exit Slot (Bottom Center-Right)
            translate([16, y_wall_in + 6, z_pivot - frame_h/2 - 1])
                cube([24, 15, wall_t + 4]);

            // F. Buzzer Acoustic Sound Grille Slots (Bottom-Right Wall)
            for (bx = [48 : 5 : 73]) {
                translate([bx, y_wall_in + 8, z_pivot - frame_h/2 - 1])
                    cube([2.2, 12, wall_t + 4]);
            }

            // G. Rear Thermal Ventilation Slots (Left & Right Flanks clear of dock)
            for (sx = [-80, -72, -64, 62, 70, 78]) {
                translate([sx, y_wall_out - 1, z_pivot - 10])
                    cube([3.2, wall_t + 2, 42]);
            }

            // H. Corner M3 Assembly Through-Holes
            for (sx = [-frame_w/2 + 6, frame_w/2 - 6], sz = [z_pivot - frame_h/2 + 6, z_pivot + frame_h/2 - 6]) {
                translate([sx, y_wall_out - 1, sz])
                    rotate([-90, 0, 0])
                    cylinder(h = wall_t + 4, d = 3.2);
            }
        }

        // 2. Internal Features Added AFTER Hollowing (Never Erased!)
        // Corner M3 Mounting Pillars bridging back wall to front bezel
        for (sx = [-frame_w/2 + 6, frame_w/2 - 6], sz = [z_pivot - frame_h/2 + 6, z_pivot + frame_h/2 - 6]) {
            difference() {
                translate([sx - 4, y_wall_in, sz - 4])
                    cube([8, rear_cavity_d, 8]);
                translate([sx, y_wall_in - 1, sz])
                    rotate([-90, 0, 0])
                    cylinder(h = rear_cavity_d + 2, d = 3.0);
            }
        }

        // Internal NodeMCU ESP-32S Standoffs (Left Bay: X = [-67, -41], Z = [66, 116])
        for (ex = [-67, -41], ez = [66, 116]) {
            difference() {
                translate([ex, y_wall_in, ez])
                    rotate([-90, 0, 0])
                    cylinder(h = 6, d = 5.5);
                translate([ex, y_wall_in + 1, ez])
                    rotate([-90, 0, 0])
                    cylinder(h = 6, d = 2.4);
            }
        }

        // Internal Buzzer Mounting Post (Right Bay: X = 56, Z = 72)
        translate([56, y_wall_in, 72])
            rotate([-90, 0, 0])
            cylinder(h = 6, d = 6.0);

        // Internal PN532 NFC Cradle (Positioned directly behind upper screen + ferrite recess)
        difference() {
            translate([-25, y_front - 11, z_pivot + 11])
                cube([50, 10.5, 45]);
            // Front-facing PCB seat & Ferrite RF coupling pocket toward LCD back
            translate([-21.5, y_front - 7.5, z_pivot + 13.5])
                cube([43, 8.5, 41]);
        }
    }
}

// ============================================================================
// FULL ASSEMBLY RENDERING & VIEW SELECTION
// ============================================================================
if (view_mode == "assembled") {
    color("#334155") wall_rail_mount();
    translate([0, 0, height_offset_z]) {
        color("#475569") height_tilt_arm();
        translate([0, y_pivot, z_pivot])
            rotate([tilt_angle_deg, 0, 0])
            translate([0, -y_pivot, -z_pivot]) {
                color("#0284c7") quick_release_wedge();
                color("#1e293b") rear_circuit_housing();
                color("#0f172a") display_front_bezel();
            }
    }
} else if (view_mode == "exploded") {
    color("#334155") wall_rail_mount();
    translate([0, 35, 0])  color("#475569") height_tilt_arm();
    translate([0, 75, 0])  color("#0284c7") quick_release_wedge();
    translate([0, 120, 0]) color("#1e293b") rear_circuit_housing();
    translate([0, 165, 0]) color("#0f172a") display_front_bezel();
} else if (view_mode == "part1") {
    wall_rail_mount();
} else if (view_mode == "part2") {
    height_tilt_arm();
} else if (view_mode == "part3") {
    quick_release_wedge();
} else if (view_mode == "part4") {
    display_front_bezel();
} else if (view_mode == "part5") {
    rear_circuit_housing();
}
