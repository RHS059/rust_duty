"""Walkable, furnished American downtown assembled from the b21 modular kit.

Coordinates and callback arguments use game-space Y-up metres.  Source assets are
bottom-centred, while add_box takes centre and dimensions.  Boxes prefixed
COLLIDER:: are collision-only; all other boxes are visible geometry.  No asset
bounds are used as wall or floor collision proxies.
"""
from math import pi, ceil, degrees

FLOOR_Y = 0.15
STORY = 3.2
WALL_HEIGHT = 3.0
STAIR_RISE = 0.2
STAIR_TREAD = 0.36

# Names are exposed to the caller for storefront lettering / navigation.
SPECS = [
    ("Union Coffee", "cafe", 2, (0.20, .33, .30)),
    ("Franklin Books", "bookshop", 3, (.37, .25, .18)),
    ("Corner Market", "market", 1, (.30, .42, .26)),
    ("Madison Pharmacy", "pharmacy", 4, (.29, .43, .47)),
    ("Main Street Diner", "diner", 2, (.52, .23, .19)),
    ("Alder & Co. Hardware", "hardware", 3, (.41, .34, .24)),
    ("Downtown Post", "post", 2, (.21, .32, .48)),
    ("Rosewood Florist", "florist", 1, (.38, .43, .28)),
    ("Liberty Bakery", "bakery", 3, (.55, .38, .24)),
    ("Elm Street Outfitters", "outfitters", 2, (.31, .37, .34)),
    ("Civic Arts Hall", "gallery", 4, (.43, .43, .46)),
    ("West End Music", "music", 2, (.36, .26, .43)),
    ("Grove Neighborhood Office", "office", 4, (.34, .37, .41)),
    ("Maple Delicatessen", "deli", 2, (.46, .31, .23)),
    ("Parkside Sports", "sports", 3, (.28, .39, .47)),
    ("The Brass Lantern", "pub", 3, (.29, .34, .24)),
]


class Building:
    def __init__(self, asset, box, records, index, cx, cz, south, spec):
        self.add_asset, self.add_box = asset, box
        self.cx, self.cz = cx, cz
        self.flip = -1 if south else 1
        self.yaw = pi if south else 0
        self.index = index
        self.name, self.kind, self.stories, self.accent = spec
        self.tag = f"B{index + 1:02d}"
        self.meta = dict(id=self.tag, name=self.name, kind=self.kind,
                         center=[cx, FLOOR_Y, cz], width=16., depth=16.,
                         stories=self.stories, floor_levels=[FLOOR_Y+STORY*n for n in range(self.stories)],
                         entrances=[], stairs=[], floor_holes=[], rooms=[], routes=[], signs=[])
        records.append(self.meta)

    def p(self, x, y, z):
        return [self.cx+self.flip*x, y, self.cz+self.flip*z]

    def a(self, name, x, y, z, yaw=0, scale=(1, 1, 1), collider=False):
        self.add_asset(name, *self.p(x, y, z), yaw=degrees(self.yaw+yaw), scale=scale, collider=collider)

    def b(self, label, x, y, z, w, h, d, color=(.64, .61, .54), solid=True):
        if min(w, h, d) <= 0:
            return
        self.add_box(f"{self.tag}/{label}", self.p(x, y, z), [w, h, d], color, solid=solid)

    def c(self, label, x, y, z, w, h, d):
        self.add_box(f"COLLIDER::{self.tag}/{label}", self.p(x, y, z), [w, h, d], (.66, .62, .55), solid=True)

    def wall(self, x, y, z, width=4, style="solid", side=False):
        """One true kitwall; exact independent boxes follow opening topology."""
        if style == "window":
            model, opening = f"b21_wall_window_opening_{width}m", (2 if width == 4 else 1, .9, 1.4)
        elif style == "door":
            model, opening = "b21_wall_double_door_opening_4m", (2., 0., 2.2)
        elif style == "store":
            model, opening = "b21_wall_storefront_opening_4m", (3.6, 0., 2.6)
        else:
            model, opening = f"b21_wall_solid_{width}m", None
        yaw = pi/2 if side else 0
        self.a(model, x, y, z, yaw)

        def block(label, u, cy, ww, hh, thick=.2):
            if side:
                self.c(label, x, y+cy, z-u, thick, hh, ww)
            else:
                self.c(label, x+u, y+cy, z, ww, hh, thick)
        if not opening:
            block("wall", 0, 1.5, width, 3.)
        else:
            ow, sill, oh = opening
            for sign in (-1, 1):
                block("wall_jamb", sign*(width+ow)/4, 1.5, (width-ow)/2, 3.)
            if sill:
                block("window_sill_wall", 0, sill/2, ow, sill)
            block("opening_lintel", 0, (sill+oh+3)/2, ow, 3-sill-oh)
            if style in ("window", "store"):
                if style == "store":
                    window = "b21_window_shopfront_3_6m"
                elif width == 2:
                    window = "b21_window_double_hung_1m"
                else:
                    window = ("b21_window_paired_2m", "b21_window_sliding_2m", "b21_window_fixed_2m")[self.index%3]
                self.a(window, x, y+sill, z, yaw)
                block("window_glazing", 0, sill+oh/2, ow, oh, .065)
                if sill:
                    self.a("b21_window_sill_2m" if width == 4 else "b21_window_sill_1m", x, y+sill-.04, z, yaw)
            elif style == "door":
                self.a("b21_door_empty_frame_1m", x, y, z, yaw, (2, 1, 1))
                for sign in (-1, 1):
                    block("doorframe_jamb", sign*.95, 1.1, .1, 2.2, .18)
                block("doorframe_header", 0, 2.175, 2, .05, .18)

    def floor_region(self, x0, x1, z0, z1, y, timber=False, ceiling=True):
        """Tile a rectangular region. Stair openings are omitted in both systems."""
        self.c("floor_slab", (x0+x1)/2, y-.1, (z0+z1)/2, x1-x0, .2, z1-z0)
        nx, nz = ceil((x1-x0)/4), ceil((z1-z0)/4)
        tw, td = (x1-x0)/nx, (z1-z0)/nz
        floor = "b21_floor_timber_4x4m" if timber else "b21_floor_concrete_4x4m"
        for ix in range(nx):
            for iz in range(nz):
                x, z = x0+(ix+.5)*tw, z0+(iz+.5)*td
                self.a(floor, x, y-.2, z, scale=(tw/4, 1, td/4))
                if ceiling:
                    self.a("b21_ceiling_plain_4x4m", x, y-.27, z, scale=(tw/4, .7, td/4))

    def floor(self, level, hole):
        y = FLOOR_Y+level*STORY
        timber = level > 0 and self.index % 3 == 0
        if hole:
            # x 2.8..7.2, z 1.6..6.9 is completely absent, including its ceiling.
            for rect in [(-8, 2.8, -8, 8), (2.8, 7.2, -8, 1.6), (2.8, 7.2, 6.9, 8), (7.2, 8, -8, 8)]:
                self.floor_region(*rect, y, timber, level > 0)
            p0,p1=self.p(2.8,y,1.6),self.p(7.2,y,6.9)
            self.meta['floor_holes'].append(dict(level=level, min=[min(a,b) for a,b in zip(p0,p1)], max=[max(a,b) for a,b in zip(p0,p1)]))
        else:
            self.floor_region(-8, 8, -8, 8, y, timber, level > 0)

    def shell(self):
        for n in range(self.stories):
            y = FLOOR_Y+n*STORY
            self.floor(n, n > 0)
            for j, x in enumerate((-6, -2, 2, 6)):
                self.wall(x, y, -8, style=("door" if j == 2 else "store") if n == 0 else "window")
                self.wall(x, y, 8, style="door" if n == 0 and j == 1 else "window")
            for x in (-8, 8):
                for z in (-6, -2, 2, 6):
                    self.wall(x, y, z, style="window" if n > 0 or z < 0 else "solid", side=True)
            # Colored masonry piers and projecting belt courses distinguish every address.
            for x in (-8, -4, 0, 4, 8):
                self.b("facade_pilaster", x, y+1.5, -8.14, .24, 3, .17, self.accent)
            for z in (-8.11, 8.11):
                self.b("belt_course", 0, y+3.06, z, 16.3, .16, .3, self.accent)
            self.b("left_belt", -8.11, y+3.06, 0, .3, .16, 16.1, self.accent)
            self.b("right_belt", 8.11, y+3.06, 0, .3, .16, 16.1, self.accent)
        self.floor(self.stories, False)
        roof = FLOOR_Y+self.stories*STORY
        for z in (-8, 8):
            self.b("roof_parapet", 0, roof+.34, z, 16.3, .68, .32, self.accent)
            self.b("stone_coping", 0, roof+.71, z, 16.5, .13, .46, (.67,.63,.53))
        for x in (-8, 8):
            self.b("roof_parapet", x, roof+.34, 0, .32, .68, 16, self.accent)
            self.b("stone_coping", x, roof+.71, 0, .46, .13, 16, (.67,.63,.53))
        self.a("b05_rooftop_packaged_hvac", -4, roof, 3, collider=True)
        self.a("b05_mushroom_roof_exhaust", 4.2, roof, -1.5)
        if self.index%2:
            self.a("b12_masonry_chimney_stack", -6, roof, 5.5)
        if self.index%3 == 0:
            for x in (-6, -3, 0, 3, 6):
                self.a("b12_dentil_cornice_section", x, roof-.07, -8.19, scale=(1, .8, 1))
        # Broad signboard sits above glass, without crossing the entry opening.
        self.b("shop_signboard", 0, 2.98, -8.3, 14.9, .46, .12, self.accent)
        self.meta['signs'].append(dict(text=self.name, position=self.p(0, 2.98, -8.375), yaw=degrees(self.yaw), width=14.2, height=.35))
        for x in (-6, -2, 6):
            self.a("b12_canvas_wedge_shop_awning" if self.index%2 else "b12_retractable_shop_awning", x, 2.77, -8.5, scale=(.95,.8,.9))
        for x in (.7, 3.3):
            self.a("b18_coach_house_wall_lantern", x, 2.15, -8.25, scale=(.65,.65,.65))
        self.b("front_entry_apron",2,.075,-10.1,3.2,.15,4.2,(.66,.65,.59))
        self.b("service_entry_apron",-2,.075,8.85,2.8,.15,1.7,(.62,.61,.56))
        for x, z, inward in [(2, -8, 1), (-2, 8, -1)]:
            self.meta['entrances'].append(dict(position=self.p(x,FLOOR_Y,z), width=1.8, height=2.15, inward=[0,0,self.flip*inward]))
        self.a("b14_recessed_apartment_mail_wall", 6.9, 1.1, -7.7, scale=(.7,.7,.7))

    def railing(self, label, x, y, z, length, along_z=True):
        metal=(.16,.18,.18)
        self.b(label+"_top",x,y+1.02,z,.075 if along_z else length,.085,length if along_z else .075,metal)
        for t in (-.5,0,.5):
            self.b(label+"_post", x if along_z else x+t*length,y+.50,z+t*length if along_z else z,.065,1,.065,metal)

    def stairs(self):
        for n in range(self.stories-1):
            y = FLOOR_Y+n*STORY
            path=[self.p(5.95,y,.5), self.p(5.95,y,1.28)]
            for i in range(8):
                top = (i+1)*.2
                z = 1.6+(i+.5)*.36
                self.b(f"stairs_{n}_A_{i}", 5.95, y+top-.1, z, 1.7, .2, .36, (.48,.45,.39))
                self.b("step_nosing",5.95,y+top+.007,z-.16,1.72,.014,.045,(.72,.65,.44),False)
                path.append(self.p(5.95,y+top,z))
                for x in (5.06,6.84):
                    self.b("stair_A_handgrip",x,y+top+.97,z,.07,.08,.375,(.14,.17,.17))
                    if i%2==0:
                        self.b("stair_A_baluster",x,y+top+.46,z,.055,.94,.055,(.18,.2,.2))
            self.b("half_landing",4.9,y+1.5,5.6,4.0,.2,2.24,(.50,.48,.42))
            path.extend([self.p(5.95,y+1.6,5.2),self.p(3.85,y+1.6,5.2)])
            for i in range(8):
                top=1.6+(i+1)*.2
                z=4.48-(i+.5)*.36
                # Thin stair slabs preserve usable volume and exact 3.2m overhead spacing.
                self.b(f"stairs_{n}_B_{i}",3.85,y+top-.1,z,1.7,.2,.36,(.48,.45,.39))
                self.b("step_nosing",3.85,y+top+.007,z+.16,1.72,.014,.045,(.72,.65,.44),False)
                path.append(self.p(3.85,y+top,z))
                for x in (2.96,4.74):
                    self.b("stair_B_handgrip",x,y+top+.97,z,.07,.08,.375,(.14,.17,.17))
                    if i%2==0:
                        self.b("stair_B_baluster",x,y+top+.46,z,.055,.94,.055,(.18,.2,.2))
            path.extend([self.p(3.85,y+3.2,1.26),self.p(3.85,y+3.2,.5)])
            self.railing("rear_landing_guard",4.9,y+1.6,6.72,4.0,False)
            self.railing("rear_landing_right",6.95,y+1.6,5.6,2.24)
            self.railing("rear_landing_left",2.86,y+1.6,5.6,2.24)
            self.meta['stairs'].append(dict(from_floor=n,to_floor=n+1,rise=.2,tread=.36,width=1.7,headroom_min=2.93,path=path))
        # Upper-floor hole guards stop people stepping directly into the shaft.
        for n in range(1,self.stories):
            y=FLOOR_Y+n*STORY
            self.railing("shaft_left",2.72,y,4.28,5.36)
            self.railing("shaft_right",7.28,y,4.28,5.36)
            self.railing("shaft_rear",5,y,6.99,4.5,False)
            # Front edge gap at x3..4.7 is the actual arrival from flight B.
            # x5.1..6.8 stays open for the next upward flight on intermediate floors.
            if n == self.stories-1:
                self.railing("top_shaft_front_right",6.05,y,1.54,2.25,False)

    def table(self,x,z,y=FLOOR_Y,kind="cafe"):
        self.a("b10_round_bistro_pedestal_table",x,y,z,collider=True)
        for dx, dz, yaw in [(0,-.75,0),(0,.75,pi)]:
            self.a("b10_woven_metal_cafe_chair",x+dx,y,z+dz,yaw,collider=True)
        self.a("b16_takeaway_coffee_cup" if kind=="cafe" else "b16_fluted_paper_plate",x+.2,y+.762,z+.07)
        self.a("b16_folded_newspaper",x-.12,y+.762,z-.1)

    def counter(self,x,z,length=3.,y=FLOOR_Y):
        self.b("counter_base",x,y+.46,z,length,.92,.72,self.accent)
        self.b("countertop",x,y+.96,z,length+.08,.08,.84,(.38,.30,.22))
        self.a("b14_countertop_parcel_postage_scale",x+.5,y+1.,z)

    def shelf(self,x,z,items,y=FLOOR_Y,yaw=0):
        # Shelf structure plus authentic catalogue stock, leaving broad shop aisles.
        for sx in (-.87,.87):
            self.b("shelf_side",x+sx,y+1.05,z,.08,2.1,.52,(.30,.25,.18))
        for sy in (.15,.8,1.45,2.05):
            self.b("shelf_board",x,y+sy,z,1.8,.07,.52,(.44,.34,.22))
        for j,item in enumerate(items):
            self.a(item,x+(-.48 if j%2==0 else .48),y+(.185,.835,1.485)[(j//2)%3],z, yaw,scale=(1,1,1))

    def shop(self):
        y=FLOOR_Y
        # Main path keeps a 2m-wide central entry/aisle and clear rear door route.
        route=[self.p(2,y,-9),self.p(2,y,-6.4),self.p(2,y,-1),self.p(5.95,y,-1),self.p(5.95,y,.5)]
        self.meta['routes'].append(dict(kind="entrance_to_stair",level=0,path=route))
        self.meta['routes'].append(dict(kind="rear_exit",level=0,path=[self.p(2,y,-1),self.p(-2,y,-1),self.p(-2,y,7),self.p(-2,y,9.3)]))
        # Back-room partition with genuine broad opening at x=-2; no glass.
        for x in (-6,-2):
            self.wall(x,y,3.8,style="door" if x==-2 else "solid")
        self.meta['rooms'].append(dict(name="Stockroom",level=0,center=self.p(-4,y,6),entrance=self.p(-2,y,3.8)))
        self.a("b14_braced_wood_shipping_crate",-6.4,y,6.7,collider=True)
        self.a("b14_parcel_hand_truck",-4.9,y,6.8,collider=True)
        self.a("b14_stackable_attached_lid_delivery_tote",-6.4,y+1.105,6.7)
        self.counter(-4.5,1.6,4.)
        self.a("b10_cafe_bar_stool_with_back",-5,y,2.5,pi,collider=True)
        self.a("b10_bottled_drink_vending_machine",7.2,y,-.7,pi/2,collider=True)
        k=self.kind
        if k in ("cafe","diner","bakery","deli","pub"):
            for x,z in [(-5.8,-5.8),(-2.3,-5.8),(-5.8,-2.8),(-2.3,-2.8),(5.8,-5.5)]:
                self.table(x,z,kind="cafe" if k in ("cafe","bakery") else "food")
            main={"cafe":"b10_sidewalk_coffee_kiosk","diner":"b10_commercial_flat_top_griddle_cart","bakery":"b10_bakery_sidewalk_glass_case","deli":"b10_taco_preparation_service_station","pub":"b10_sidewalk_condiment_service_station"}[k]
            self.a(main,-6.4,y,.4,collider=True)
            self.a("b10_donut_shop_display_counter" if k in ("bakery","cafe") else "b10_restaurant_hostess_station",5.8,y,-2.3,pi/2,collider=True)
            self.a("b10_portable_commercial_handwash_sink",-7.2,y,2.5,collider=True)
            for i in range(3):
                self.a("b16_baguette_in_paper_sleeve" if k=="bakery" else "b16_takeaway_coffee_cup",-5.5+i*.7,y+1.01,1.6)
        elif k=="bookshop":
            for x,z in [(-6.4,-5.3),(-3.9,-5.3),(-6.4,-2.7),(-3.9,-2.7),(5.7,-5.4)]:
                self.a("b10_outdoor_bookshop_cart",x,y,z,collider=True)
            self.a("b10_sidewalk_magazine_ladder",-6.7,y,.2,collider=True)
            self.a("b10_greeting_card_spinner_rack",5.8,y,-2.4,collider=True)
            self.table(-3.2,-1.6)
        elif k in ("market","pharmacy"):
            for x,z in [(-6,-5),(-3,-5),(-6,-2.5),(5.6,-5.4)]:
                self.a("b10_tiered_sidewalk_produce_stand" if k=="market" else "b10_greeting_card_spinner_rack",x,y,z,collider=True)
            self.shelf(5.7,-2.7,["b16_ribbed_water_bottle","b16_gable_top_milk_carton","b16_square_juice_bottle","b16_six_egg_carton","b16_sealed_potato_chip_bag","b16_juice_box_with_straw"])
            self.a("b10_bulk_nut_dispenser_stand",-6.5,y,.2,collider=True)
        elif k=="hardware":
            stock=["b06_adjustable_wrench","b06_retractable_tape_measure","b17_handheld_torch_flashlight","b17_outdoor_two_way_radio"]
            for x,z in [(-6,-5),(-3,-5),(-6,-2.5),(5.7,-5.4)]:
                self.shelf(x,z,stock)
            self.a("b14_open_slatted_parts_crate",5.8,y,-2.5,collider=True)
        elif k=="post":
            for x,z in [(-6.2,-5.2),(-3.5,-5.2),(-6.2,-2.5)]:
                self.a("b14_mobile_letter_sorting_cubbies",x,y,z,collider=True)
            self.a("b14_electronic_parcel_locker",5.9,y,-5.6,pi/2,collider=True)
            self.a("b14_postal_rolling_canvas_hamper",5.9,y,-3.,collider=True)
            self.a("b14_mail_sack_sorting_stand",-3.6,y,-2.3,collider=True)
        elif k=="florist":
            for x,z in [(-6,-5.5),(-3,-5.5),(-6,-2.5),(-3,-2.5),(5.8,-5.4),(5.8,-2.6)]:
                self.a("b10_florist_bucket_sidewalk_display",x,y,z,collider=True)
        elif k in ("outfitters","sports"):
            for x,z in [(-6,-5.5),(-3,-5.5),(-6,-2.4),(-3,-2.4)]:
                self.a("b10_rolling_sidewalk_garment_rack",x,y,z,collider=True)
            self.shelf(5.8,-5.3,["b17_seamed_basketball","b17_laced_american_football","b17_baseball_fielders_glove","b17_stitched_baseball","b17_vented_bicycle_helmet","b17_zippered_day_backpack"])
            self.a("b10_rotating_sunglasses_display",5.8,y,-2.4,collider=True)
        elif k in ("music","gallery"):
            for x,z in [(-5.7,-5),(-2.5,-5),(-5.7,-2)]:
                self.b("exhibit_plinth",x,y+.42,z,1.1,.84,1.1,(.61,.59,.53))
                if k=="music":
                    self.a("b20_stage_floor_monitor_wedge",x,y+.84,z,collider=True)
                else:
                    self.a("b18_interlocking_steel_ribbon_sculpture",x,y+.84,z,scale=(.37,.37,.37))
            self.a("b20_portable_audio_mixing_console",5.7,y,-5.5,collider=True)
            self.a("b20_pa_loudspeaker_on_tripod",6.7,y,-2.5,collider=True)
        else:
            for x,z in [(-6,-5.4),(-2.4,-5.4),(-6,-2.5),(5.7,-5.5)]:
                self.desk(x,z,y)
        self.meta['rooms'].append(dict(name=self.name+" shop floor",level=0,center=self.p(-2,y,-4),entrance=self.p(2,y,-8)))

    def desk(self,x,z,y):
        self.a("b20_folding_banquet_service_table",x,y,z,collider=True)
        self.a("b10_woven_metal_cafe_chair",x,y,z+.83,pi,collider=True)
        self.a("b16_folded_newspaper",x+.35,y+.78,z)
        self.a("b16_takeaway_coffee_cup",x-.4,y+.78,z)
        # Simple office monitor: catalogue supplies furniture; small geometry supplies screens.
        self.b("monitor_foot",x,y+.8,z-.12,.24,.035,.18,(.16,.18,.19),False)
        self.b("monitor_stand",x,y+.94,z-.16,.06,.25,.05,(.16,.18,.19),False)
        self.b("monitor_screen",x,y+1.13,z-.16,.48,.31,.045,(.10,.19,.23),False)

    def apartment(self,x,z,y):
        self.b("bed_frame",x,y+.23,z,1.8,.46,2.3,(.30,.22,.15))
        self.b("mattress",x,y+.52,z,1.74,.18,2.22,(.83,.8,.66))
        self.b("duvet",x,y+.64,z+.25,1.77,.07,1.73,self.accent,False)
        self.b("pillow",x,y+.67,z-.78,1.35,.16,.42,(.94,.89,.75),False)
        self.a("b17_ribbed_rolling_suitcase",x+1.6,y,z-.6,collider=True)
        self.a("b11_woven_patio_armchair",x+1.8,y,z+1.6,pi/2,collider=True)
        self.a("b17_folded_picnic_blanket",x,y+.68,z+.4)

    def upper_rooms(self):
        for n in range(1,self.stories):
            y=FLOOR_Y+n*STORY
            for x in (-6,-2,2,6):
                self.wall(x,y,-2,style="door" if x in (-6,2) else "solid")
            self.wall(0,y,-6,4,side=True)
            self.wall(0,y,-3,2,side=True)
            for x in (-6,-2):
                self.wall(x,y,1.5,style="door" if x==-2 else "solid")
            # A 2.8m-wide hall serves every room and the open stair landing.
            for room,x,z,entry in [("Front west",-4,-5,(-6,-2)),("Front east",4,-5,(2,-2)),("Rear studio",-4,4.9,(-2,1.5))]:
                home=(self.index+n)%3 == 0
                self.meta['rooms'].append(dict(name=room+(" apartment" if home else " office"),level=n,center=self.p(x,y,z),entrance=self.p(entry[0],y,entry[1])))
                if home:
                    self.apartment(x-1.1,z-.3,y)
                else:
                    self.desk(x-1.25,z-.4,y)
                    self.desk(x+1.45,z+1.3,y)
                    self.a("b14_mobile_letter_sorting_cubbies",x+1.8,y,z-1.5,collider=True)
                self.meta['routes'].append(dict(kind="stair_to_room",level=n,path=[self.p(3.85,y,.5),self.p(entry[0],y,.5),self.p(entry[0],y,entry[1]),self.p(entry[0],y,entry[1]+(-.8 if entry[1]<0 else .8))]))
            # Small hall seating sits against the exterior, outside the clear route.
            self.a("b01_backless_boardwalk_bench",-7.45,y,-.3,pi/2,collider=True)

    def build(self):
        self.shell()
        self.stairs()
        self.shop()
        self.upper_rooms()


def build(add_asset, add_box, buildings):
    """Append sixteen complete buildings and their physical-navigation metadata."""
    i=0
    for cz in (-44,-20,20,44):
        for cx in (-44,-20,20,44):
            Building(add_asset,add_box,buildings,i,cx,cz,cz in (-20,44),SPECS[i]).build()
            i+=1
    return buildings
