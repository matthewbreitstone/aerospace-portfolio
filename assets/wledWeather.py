import json
import math
import random
import socket
import time
import urllib.parse
import urllib.request


# ============================================================
# USER SETTINGS
# ============================================================

# Change this to the IP address shown on your WLED webpage.
WLED_IP = "192.168.1.100"  # Replace with your WLED device IP

# Default WLED realtime UDP port.
WLED_UDP_PORT = 21324

# Matrix dimensions.
# Width = LEDs across each row.
# Height = number of rows.
MATRIX_WIDTH = 15
MATRIX_HEIGHT = 4

NUM_LEDS = MATRIX_WIDTH * MATRIX_HEIGHT

# LED animation frame rate.
FPS = 25

# Weather is checked immediately at startup,
# then again every 10 minutes.
WEATHER_CHECK_MINUTES = 3

# Approximate coordinates for West Lafayette, Indiana.
LATITUDE = 40.43  # Replace with your latitude
LONGITUDE = -86.93  # Replace with your longitude

# Overall brightness from 0 to 255.
# Keep this low if powering a short test strip from USB.
MAX_BRIGHTNESS = 80

# Lightning probability per animation frame during thunderstorms.
# At 25 FPS, 0.004 averages about one strike every 10 seconds.
LIGHTNING_CHANCE = 0.004

# Night-mode star settings.
# Fraction of LEDs used as stars.
STAR_DENSITY = 0.18

# Minimum and maximum twinkle speeds.
STAR_MIN_SPEED = 0.006
STAR_MAX_SPEED = 0.025


# ============================================================
# NETWORK SETUP
# ============================================================

udp_socket = socket.socket(
    socket.AF_INET,
    socket.SOCK_DGRAM
)


# ============================================================
# MATRIX MAPPING
# ============================================================

def xy_to_index(x, y):
    """
    Convert an x, y matrix coordinate into a physical LED index.

    This assumes:

    Row 0: left to right
    Row 1: right to left
    Row 2: left to right
    Row 3: right to left

    LED 0 is assumed to be at the top-left corner.
    """

    if x < 0 or x >= MATRIX_WIDTH:
        return None

    if y < 0 or y >= MATRIX_HEIGHT:
        return None

    if y % 2 == 0:
        return y * MATRIX_WIDTH + x

    return (
        y * MATRIX_WIDTH
        + MATRIX_WIDTH
        - 1
        - x
    )


def create_blank_frame():
    """Create a completely dark LED frame."""

    return [
        (0, 0, 0)
        for _ in range(NUM_LEDS)
    ]


def set_pixel(frame, x, y, color):
    """Set one pixel using matrix coordinates."""

    index = xy_to_index(x, y)

    if index is not None:
        frame[index] = color


def add_light(frame, x, y, color):
    """
    Add RGB brightness to a pixel.

    This is useful for combining a bright lightning bolt
    with a surrounding blue glow.
    """

    index = xy_to_index(x, y)

    if index is None:
        return

    old_red, old_green, old_blue = frame[index]
    add_red, add_green, add_blue = color

    frame[index] = (
        clamp(old_red + add_red),
        clamp(old_green + add_green),
        clamp(old_blue + add_blue),
    )


# ============================================================
# COLOR FUNCTIONS
# ============================================================

def clamp(value):
    """Keep an RGB value between 0 and 255."""

    return max(
        0,
        min(255, int(value))
    )


def scale_color(color, brightness):
    """
    Scale a color by effect brightness and master brightness.

    brightness should normally be between 0.0 and 1.0.
    """

    master_scale = MAX_BRIGHTNESS / 255.0
    final_scale = brightness * master_scale

    red, green, blue = color

    return (
        clamp(red * final_scale),
        clamp(green * final_scale),
        clamp(blue * final_scale),
    )


def blend_colors(color_1, color_2, amount):
    """
    Blend between two RGB colors.

    amount = 0 gives color_1.
    amount = 1 gives color_2.
    """

    amount = max(
        0.0,
        min(1.0, amount)
    )

    return (
        clamp(
            color_1[0] * (1 - amount)
            + color_2[0] * amount
        ),
        clamp(
            color_1[1] * (1 - amount)
            + color_2[1] * amount
        ),
        clamp(
            color_1[2] * (1 - amount)
            + color_2[2] * amount
        ),
    )


# ============================================================
# WLED COMMUNICATION
# ============================================================

def send_frame(frame):
    """
    Send a complete RGB frame to WLED using UDP realtime mode.

    The first byte selects the DRGB protocol.
    The second byte is the realtime timeout in seconds.
    """

    packet = bytearray([2, 2])

    for red, green, blue in frame:
        packet.extend([
            clamp(red),
            clamp(green),
            clamp(blue),
        ])

    udp_socket.sendto(
        packet,
        (WLED_IP, WLED_UDP_PORT)
    )


# ============================================================
# WEATHER API
# ============================================================

def get_current_weather():
    """
    Get current weather from Open-Meteo.

    This uses Python's built-in urllib library,
    so no pip installation is required.
    """

    parameters = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "current": (
            "weather_code,"
            "temperature_2m,"
            "is_day,"
            "precipitation"
        ),
        "temperature_unit": "fahrenheit",
        "timezone": "auto",
    }

    query = urllib.parse.urlencode(parameters)

    url = (
        "https://api.open-meteo.com/v1/forecast?"
        + query
    )

    with urllib.request.urlopen(
        url,
        timeout=15
    ) as response:

        response_text = (
            response
            .read()
            .decode("utf-8")
        )

        weather_data = json.loads(
            response_text
        )

    return weather_data["current"]


def weather_code_to_condition(weather_code):
    """Convert an Open-Meteo weather code into an effect."""

    if weather_code == 0:
        return "clear"

    if weather_code in (1, 2):
        return "partly_cloudy"

    if weather_code == 3:
        return "cloudy"

    if weather_code in (45, 48):
        return "fog"

    if weather_code in (
        51, 53, 55,
        56, 57,
        61, 63, 65,
        66, 67,
        80, 81, 82,
    ):
        return "rain"

    if weather_code in (
        71, 73, 75, 77,
        85, 86,
    ):
        return "snow"

    if weather_code in (
        95, 96, 99
    ):
        return "storm"

    return "cloudy"


# ============================================================
# NIGHT STAR EFFECT
# ============================================================

def create_stars():
    """Create a fixed field of independently twinkling stars."""

    star_count = max(
        1,
        int(NUM_LEDS * STAR_DENSITY)
    )

    star_positions = random.sample(
        range(NUM_LEDS),
        min(star_count, NUM_LEDS)
    )

    stars = []

    for index in star_positions:
        stars.append({
            "index": index,
            "brightness": random.uniform(
                0.05,
                0.65
            ),
            "target": random.uniform(
                0.25,
                1.0
            ),
            "speed": random.uniform(
                STAR_MIN_SPEED,
                STAR_MAX_SPEED
            ),
        })

    return stars


def create_night_star_frame(stars):
    """Create a dark sky with softly twinkling stars."""

    frame = create_blank_frame()

    # Very dim blue-black background so the ceiling is not fully black.
    background = scale_color(
        (0, 3, 18),
        0.22
    )

    for y in range(MATRIX_HEIGHT):
        for x in range(MATRIX_WIDTH):
            set_pixel(
                frame,
                x,
                y,
                background
            )

    for star in stars:

        brightness = star["brightness"]
        target = star["target"]
        speed = star["speed"]

        if brightness < target:
            brightness += speed
        else:
            brightness -= speed

        if abs(brightness - target) <= speed:
            star["target"] = random.uniform(
                0.08,
                1.0
            )
            star["speed"] = random.uniform(
                STAR_MIN_SPEED,
                STAR_MAX_SPEED
            )

        brightness = max(
            0.03,
            min(1.0, brightness)
        )

        star["brightness"] = brightness

        # Slight blue tint makes the stars look less harsh.
        frame[star["index"]] = scale_color(
            (235, 245, 255),
            brightness
        )

    return frame


# ============================================================
# CLEAR SKY EFFECT
# ============================================================

def create_clear_frame(frame_number, is_day):
    """Create a moving blue sky effect."""

    frame = create_blank_frame()

    if is_day:
        dark_color = (15, 75, 210)
        light_color = (80, 190, 255)

    else:
        dark_color = (0, 3, 25)
        light_color = (15, 30, 100)

    for y in range(MATRIX_HEIGHT):
        for x in range(MATRIX_WIDTH):

            wave = math.sin(
                x * 0.45
                + y * 0.22
                + frame_number * 0.035
            )

            blend_amount = (
                wave + 1
            ) / 2

            brightness = (
                0.60
                + 0.12 * wave
            )

            color = blend_colors(
                dark_color,
                light_color,
                blend_amount
            )

            set_pixel(
                frame,
                x,
                y,
                scale_color(
                    color,
                    brightness
                )
            )

    return frame


# ============================================================
# PARTLY CLOUDY EFFECT
# ============================================================

def create_partly_cloudy_frame(
    frame_number,
    is_day
):
    """Create drifting clouds over a blue background."""

    frame = create_blank_frame()

    if is_day:
        sky_color = (20, 100, 230)
        cloud_color = (200, 220, 235)

    else:
        sky_color = (1, 7, 30)
        cloud_color = (55, 65, 95)

    cloud_x = (
        frame_number * 0.08
    ) % (
        MATRIX_WIDTH + 8
    ) - 4

    second_cloud_x = (
        frame_number * 0.045
        + MATRIX_WIDTH / 2
    ) % (
        MATRIX_WIDTH + 10
    ) - 5

    for y in range(MATRIX_HEIGHT):
        for x in range(MATRIX_WIDTH):

            first_distance = math.sqrt(
                (x - cloud_x) ** 2
                + (
                    (
                        y
                        - MATRIX_HEIGHT * 0.35
                    ) * 1.4
                ) ** 2
            )

            second_distance = math.sqrt(
                (x - second_cloud_x) ** 2
                + (
                    (
                        y
                        - MATRIX_HEIGHT * 0.70
                    ) * 1.3
                ) ** 2
            )

            first_cloud = max(
                0.0,
                1.0
                - first_distance / 3.5
            )

            second_cloud = max(
                0.0,
                1.0
                - second_distance / 4.0
            )

            cloud_amount = (
                max(
                    first_cloud,
                    second_cloud
                )
                * 0.85
            )

            color = blend_colors(
                sky_color,
                cloud_color,
                cloud_amount
            )

            set_pixel(
                frame,
                x,
                y,
                scale_color(
                    color,
                    0.65
                )
            )

    return frame


# ============================================================
# CLOUDY EFFECT
# ============================================================

def create_cloudy_frame(frame_number):
    """Create slowly shifting gray clouds."""

    frame = create_blank_frame()

    dark_cloud = (20, 25, 40)
    light_cloud = (115, 125, 145)

    for y in range(MATRIX_HEIGHT):
        for x in range(MATRIX_WIDTH):

            wave_1 = math.sin(
                x * 0.55
                + y * 0.30
                + frame_number * 0.025
            )

            wave_2 = math.sin(
                x * 0.22
                - y * 0.50
                - frame_number * 0.017
            )

            cloud_amount = (
                wave_1
                + wave_2
                + 2
            ) / 4

            color = blend_colors(
                dark_cloud,
                light_cloud,
                cloud_amount
            )

            brightness = (
                0.42
                + cloud_amount * 0.18
            )

            set_pixel(
                frame,
                x,
                y,
                scale_color(
                    color,
                    brightness
                )
            )

    return frame


# ============================================================
# FOG EFFECT
# ============================================================

def create_fog_frame(frame_number):
    """Create slow-moving fog bands."""

    frame = create_blank_frame()

    dark_fog = (55, 65, 75)
    light_fog = (185, 195, 200)

    for y in range(MATRIX_HEIGHT):
        for x in range(MATRIX_WIDTH):

            wave_1 = math.sin(
                x * 0.30
                + y * 0.12
                + frame_number * 0.016
            )

            wave_2 = math.sin(
                x * 0.10
                - y * 0.35
                - frame_number * 0.009
            )

            amount = (
                wave_1
                + wave_2
                + 2
            ) / 4

            color = blend_colors(
                dark_fog,
                light_fog,
                amount
            )

            set_pixel(
                frame,
                x,
                y,
                scale_color(
                    color,
                    0.40
                )
            )

    return frame


# ============================================================
# RAIN PARTICLES
# ============================================================

def create_raindrops():
    """Create rain particles above and inside the matrix."""

    raindrops = []

    drop_count = max(
        4,
        MATRIX_WIDTH // 2
    )

    for _ in range(drop_count):
        raindrops.append({
            "x": random.randrange(
                MATRIX_WIDTH
            ),
            "y": random.uniform(
                -MATRIX_HEIGHT,
                MATRIX_HEIGHT
            ),
            "speed": random.uniform(
                0.25,
                0.65
            ),
        })

    return raindrops


def create_rain_frame(
    frame_number,
    raindrops
):
    """Create rain falling vertically through the matrix."""

    frame = create_blank_frame()

    for y in range(MATRIX_HEIGHT):
        for x in range(MATRIX_WIDTH):

            cloud_wave = math.sin(
                x * 0.40
                + y * 0.22
                + frame_number * 0.018
            )

            background = scale_color(
                (12, 22, 55),
                0.23
                + cloud_wave * 0.025
            )

            set_pixel(
                frame,
                x,
                y,
                background
            )

    for drop in raindrops:

        drop["y"] += drop["speed"]

        if drop["y"] >= MATRIX_HEIGHT + 2:

            drop["x"] = random.randrange(
                MATRIX_WIDTH
            )

            drop["y"] = random.uniform(
                -5,
                -1
            )

            drop["speed"] = random.uniform(
                0.25,
                0.65
            )

        x = int(drop["x"])
        y = int(drop["y"])

        set_pixel(
            frame,
            x,
            y,
            scale_color(
                (100, 180, 255),
                0.95
            )
        )

        set_pixel(
            frame,
            x,
            y - 1,
            scale_color(
                (25, 90, 220),
                0.70
            )
        )

        set_pixel(
            frame,
            x,
            y - 2,
            scale_color(
                (5, 35, 110),
                0.45
            )
        )

    return frame


# ============================================================
# SNOW PARTICLES
# ============================================================

def create_snowflakes():
    """Create falling snow particles."""

    snowflakes = []

    flake_count = max(
        5,
        MATRIX_WIDTH
    )

    for _ in range(flake_count):
        snowflakes.append({
            "x": random.uniform(
                0,
                MATRIX_WIDTH - 1
            ),
            "y": random.uniform(
                -MATRIX_HEIGHT,
                MATRIX_HEIGHT
            ),
            "speed": random.uniform(
                0.05,
                0.20
            ),
            "drift": random.uniform(
                -0.025,
                0.025
            ),
            "brightness": random.uniform(
                0.55,
                1.0
            ),
        })

    return snowflakes


def create_snow_frame(
    frame_number,
    snowflakes
):
    """Create falling and drifting snow."""

    frame = create_blank_frame()

    background = scale_color(
        (8, 20, 50),
        0.28
    )

    for y in range(MATRIX_HEIGHT):
        for x in range(MATRIX_WIDTH):
            set_pixel(
                frame,
                x,
                y,
                background
            )

    for flake in snowflakes:

        flake["y"] += flake["speed"]
        flake["x"] += flake["drift"]

        if flake["y"] >= MATRIX_HEIGHT:

            flake["y"] = random.uniform(
                -4,
                -1
            )

            flake["x"] = random.uniform(
                0,
                MATRIX_WIDTH - 1
            )

        if flake["x"] < 0:
            flake["x"] = MATRIX_WIDTH - 1

        if flake["x"] >= MATRIX_WIDTH:
            flake["x"] = 0

        x = int(flake["x"])
        y = int(flake["y"])

        twinkle = (
            math.sin(
                frame_number * 0.10
                + x
                + y
            ) + 1
        ) / 2

        brightness = (
            flake["brightness"]
            * (
                0.70
                + twinkle * 0.30
            )
        )

        set_pixel(
            frame,
            x,
            y,
            scale_color(
                (215, 235, 255),
                brightness
            )
        )

    return frame


# ============================================================
# THUNDERSTORM BACKGROUND
# ============================================================

def create_storm_background(frame_number):
    """Create dark moving storm clouds."""

    frame = create_blank_frame()

    for y in range(MATRIX_HEIGHT):
        for x in range(MATRIX_WIDTH):

            wave_1 = math.sin(
                x * 0.47
                + y * 0.35
                + frame_number * 0.022
            )

            wave_2 = math.sin(
                x * 0.16
                - y * 0.40
                - frame_number * 0.014
            )

            amount = (
                wave_1
                + wave_2
                + 2
            ) / 4

            color = blend_colors(
                (2, 4, 14),
                (18, 28, 65),
                amount
            )

            set_pixel(
                frame,
                x,
                y,
                scale_color(
                    color,
                    0.35
                )
            )

    return frame


def create_storm_frame(
    frame_number,
    raindrops
):
    """Create dark storm clouds and falling rain."""

    frame = create_storm_background(
        frame_number
    )

    for drop in raindrops:

        drop["y"] += (
            drop["speed"] * 1.35
        )

        if drop["y"] >= MATRIX_HEIGHT + 2:

            drop["x"] = random.randrange(
                MATRIX_WIDTH
            )

            drop["y"] = random.uniform(
                -5,
                -1
            )

            drop["speed"] = random.uniform(
                0.30,
                0.75
            )

        x = int(drop["x"])
        y = int(drop["y"])

        set_pixel(
            frame,
            x,
            y,
            scale_color(
                (90, 155, 255),
                0.90
            )
        )

        set_pixel(
            frame,
            x,
            y - 1,
            scale_color(
                (20, 60, 165),
                0.60
            )
        )

    return frame


# ============================================================
# RANDOM LIGHTNING
# ============================================================

def draw_lightning_branch(
    frame,
    start_x,
    start_y,
    general_direction,
    max_length,
    brightness
):
    """
    Draw a random side branch from the main lightning bolt.

    general_direction:
        -1 generally moves left.
         1 generally moves right.
    """

    x = start_x
    y = start_y

    for step in range(max_length):

        if not (
            0 <= x < MATRIX_WIDTH
            and 0 <= y < MATRIX_HEIGHT
        ):
            break

        branch_fade = (
            1.0
            - step / max(
                1,
                max_length
            )
        )

        current_brightness = (
            brightness
            * (
                0.50
                + branch_fade * 0.50
            )
        )

        add_light(
            frame,
            x,
            y,
            scale_color(
                (220, 235, 255),
                current_brightness
            )
        )

        add_light(
            frame,
            x - 1,
            y,
            scale_color(
                (55, 100, 255),
                current_brightness * 0.35
            )
        )

        add_light(
            frame,
            x + 1,
            y,
            scale_color(
                (55, 100, 255),
                current_brightness * 0.35
            )
        )

        horizontal_move = random.choices(
            [-1, 0, 1],
            weights=[2, 4, 2]
        )[0]

        if random.random() < 0.45:
            horizontal_move = general_direction

        x += horizontal_move

        # Branches usually move downward,
        # but sometimes move sideways for one step.
        if random.random() < 0.75:
            y += 1


def create_random_lightning_frame():
    """
    Generate a randomized main lightning bolt
    with multiple random side branches.
    """

    frame = create_storm_background(
        random.randint(0, 1000)
    )

    # Add a dim whole-cloud flash.
    cloud_flash_strength = random.uniform(
        0.05,
        0.20
    )

    for y in range(MATRIX_HEIGHT):
        for x in range(MATRIX_WIDTH):

            add_light(
                frame,
                x,
                y,
                scale_color(
                    (80, 100, 160),
                    cloud_flash_strength
                )
            )

    main_x = random.randrange(
        MATRIX_WIDTH
    )

    bolt_points = []

    x = main_x
    y = 0

    while y < MATRIX_HEIGHT:

        x += random.choices(
            [-1, 0, 1],
            weights=[2, 5, 2]
        )[0]

        x = max(
            0,
            min(
                MATRIX_WIDTH - 1,
                x
            )
        )

        bolt_points.append(
            (x, y)
        )

        add_light(
            frame,
            x,
            y,
            scale_color(
                (255, 255, 255),
                1.0
            )
        )

        add_light(
            frame,
            x - 1,
            y,
            scale_color(
                (70, 120, 255),
                0.60
            )
        )

        add_light(
            frame,
            x + 1,
            y,
            scale_color(
                (70, 120, 255),
                0.60
            )
        )

        # Occasionally create a thicker section.
        if random.random() < 0.20:

            add_light(
                frame,
                x,
                y + 1,
                scale_color(
                    (180, 210, 255),
                    0.75
                )
            )

        # Usually move down one row.
        # Occasionally skip or linger for a jagged shape.
        y += random.choices(
            [1, 1, 1, 2],
            weights=[4, 4, 4, 1]
        )[0]

    # Pick random points along the main bolt
    # where side branches will begin.
    branch_count = random.randint(
        1,
        max(
            2,
            min(
                5,
                MATRIX_HEIGHT
            )
        )
    )

    possible_branch_points = bolt_points[
        1:-1
    ]

    if possible_branch_points:

        for _ in range(branch_count):

            branch_x, branch_y = random.choice(
                possible_branch_points
            )

            direction = random.choice(
                [-1, 1]
            )

            available_length = max(
                1,
                MATRIX_HEIGHT - branch_y
            )

            branch_length = random.randint(
                1,
                available_length
            )

            branch_brightness = random.uniform(
                0.40,
                0.80
            )

            draw_lightning_branch(
                frame=frame,
                start_x=branch_x,
                start_y=branch_y,
                general_direction=direction,
                max_length=branch_length,
                brightness=branch_brightness
            )

    return frame


def show_lightning():
    """
    Display a randomized lightning sequence.

    Each flash gets a newly generated pattern,
    so the lightning can move between flashes.
    """

    flash_count = random.choice([
        1,
        2,
        2,
        3,
    ])

    for flash_number in range(
        flash_count
    ):

        lightning_frame = (
            create_random_lightning_frame()
        )

        send_frame(
            lightning_frame
        )

        time.sleep(
            random.uniform(
                0.035,
                0.090
            )
        )

        dark_frame = (
            create_storm_background(
                random.randint(
                    0,
                    1000
                )
            )
        )

        send_frame(
            dark_frame
        )

        if flash_number < flash_count - 1:

            time.sleep(
                random.uniform(
                    0.040,
                    0.160
                )
            )


# ============================================================
# MAIN PROGRAM
# ============================================================

def main():
    """Run the weather-controlled LED matrix."""

    frame_number = 0

    current_condition = "cloudy"
    is_day = True

    last_weather_check = 0.0

    weather_check_seconds = (
        WEATHER_CHECK_MINUTES * 60
    )

    rain_drops = create_raindrops()
    storm_drops = create_raindrops()
    snowflakes = create_snowflakes()
    stars = create_stars()

    frame_delay = 1 / FPS

    print("Weather matrix started.")
    print(
        f"Matrix size: "
        f"{MATRIX_WIDTH} x {MATRIX_HEIGHT}"
    )
    print(
        f"Total LEDs: {NUM_LEDS}"
    )
    print(
        f"WLED address: {WLED_IP}"
    )
    print(
        f"Weather polling: "
        f"every {WEATHER_CHECK_MINUTES} minutes"
    )
    print(
        "Press Ctrl+C to stop."
    )

    try:
        while True:

            loop_start = time.monotonic()
            current_time = time.monotonic()

            # Weather is checked immediately when the
            # program starts and then at the chosen interval.
            if (
                last_weather_check == 0
                or current_time - last_weather_check
                >= weather_check_seconds
            ):

                try:
                    weather = (
                        get_current_weather()
                    )

                    weather_code = int(
                        weather[
                            "weather_code"
                        ]
                    )

                    temperature = float(
                        weather[
                            "temperature_2m"
                        ]
                    )

                    is_day = bool(
                        weather.get(
                            "is_day",
                            1
                        )
                    )

                    current_condition = (
                        weather_code_to_condition(
                            weather_code
                        )
                    )

                    last_weather_check = (
                        current_time
                    )

                    print(
                        f"Weather code: "
                        f"{weather_code} | "
                        f"Effect: "
                        f"{current_condition} | "
                        f"Temperature: "
                        f"{temperature:.1f} F | "
                        f"Mode: "
                        f"{'day' if is_day else 'night'}"
                    )

                except Exception as error:

                    print(
                        "Weather update failed."
                    )

                    print(
                        "Continuing with effect: "
                        f"{current_condition}"
                    )

                    print(
                        f"Error: {error}"
                    )

                    # Try the weather API again
                    # in approximately one minute.
                    last_weather_check = (
                        current_time
                        - weather_check_seconds
                        + 60
                    )

            # At night, use twinkling stars only for dry weather.
            # Rain, snow, and thunderstorms still use their weather effects.
            if (
                not is_day
                and current_condition not in (
                    "rain",
                    "snow",
                    "storm",
                )
            ):

                frame = create_night_star_frame(
                    stars
                )

            # Otherwise, select the current weather animation.
            elif current_condition == "clear":

                frame = create_clear_frame(
                    frame_number,
                    is_day
                )

            elif (
                current_condition
                == "partly_cloudy"
            ):

                frame = (
                    create_partly_cloudy_frame(
                        frame_number,
                        is_day
                    )
                )

            elif current_condition == "cloudy":

                frame = create_cloudy_frame(
                    frame_number
                )

            elif current_condition == "fog":

                frame = create_fog_frame(
                    frame_number
                )

            elif current_condition == "rain":

                frame = create_rain_frame(
                    frame_number,
                    rain_drops
                )

            elif current_condition == "snow":

                frame = create_snow_frame(
                    frame_number,
                    snowflakes
                )

            elif current_condition == "storm":

                frame = create_storm_frame(
                    frame_number,
                    storm_drops
                )

                if (
                    random.random()
                    < LIGHTNING_CHANCE
                ):
                    show_lightning()

            else:

                frame = create_cloudy_frame(
                    frame_number
                )

            send_frame(frame)

            frame_number += 1

            elapsed_time = (
                time.monotonic()
                - loop_start
            )

            remaining_time = (
                frame_delay
                - elapsed_time
            )

            if remaining_time > 0:
                time.sleep(
                    remaining_time
                )

    except KeyboardInterrupt:

        print(
            "\nStopping weather matrix."
        )

        send_frame(
            create_blank_frame()
        )

    finally:

        udp_socket.close()


if __name__ == "__main__":
    main()