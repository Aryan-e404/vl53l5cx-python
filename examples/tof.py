import time
import numpy
import argparse
import os # Import os for clearing the terminal
from smbus2 import SMBus

import vl53l5cx_ctypes as vl53l5cx
from vl53l5cx_ctypes import STATUS_RANGE_VALID, STATUS_RANGE_VALID_LARGE_PULSE, DEFAULT_I2C_ADDRESS

# --- Configuration Constants ---
RESOLUTION_VAL = 8 * 8
MOTION_RESOLUTION_VAL = 8 * 8
MOTION_MIN_DISTANCE_MM = 400
MOTION_MAX_DISTANCE_MM = 1400
OBSTACLE_THRESHOLD_MM = 700

# --- Output Formatting ---
COL_WIDTH = 40

EMPTY_DISTANCE_MATRIX = numpy.full((8, 8), 0, dtype=int) # Using 0 as initial/empty
EMPTY_STATUS_MATRIX = numpy.full((8, 8), False, dtype=bool)
EMPTY_OBSTACLE_TEXT = "Waiting..."


def clear_terminal():
    """Clears the terminal screen."""
    if os.name == 'nt':
        _ = os.system('cls')
    else:
        _ = os.system('clear')

def parse_args():
    parser = argparse.ArgumentParser(description="Read data from multiple VL53L5CX ToF sensors.")
    parser.add_argument(
        '--tof_addr', metavar='ADDR', type=lambda x: int(x, 0), nargs='+',
        default=[DEFAULT_I2C_ADDRESS],
        help=f"Space-separated I2C addresses (e.g., 0x29 0x31). Default: {DEFAULT_I2C_ADDRESS:#02x}"
    )
    parser.add_argument(
        '--bus', type=int, default=None,
        help="I2C bus number (e.g., 1 or 4). If not specified, library default is used (usually bus 1)."
    )
    return parser.parse_args()

def initialize_sensor(address, i2c_bus_object=None):
    print(f"Initializing sensor at address {address:#02x}...")
    try:
        sensor = vl53l5cx.VL53L5CX(i2c_addr=address, i2c_dev=i2c_bus_object)
        print(f"Firmware uploaded for sensor {address:#02x}.")
        sensor.set_resolution(RESOLUTION_VAL)
        sensor.enable_motion_indicator(MOTION_RESOLUTION_VAL)
        sensor.set_motion_distance(MOTION_MIN_DISTANCE_MM, MOTION_MAX_DISTANCE_MM)
        sensor.start_ranging()
        print(f"Sensor {address:#02x} initialized and ranging started.")
        return sensor
    except Exception as e:
        print(f"Error initializing sensor at address {address:#02x}: {e}")
        return None

def process_sensor_data_for_display(data_packet):
    if data_packet is None:
        return EMPTY_DISTANCE_MATRIX, EMPTY_STATUS_MATRIX

    num_zones = RESOLUTION_VAL
    grid_size = int(numpy.sqrt(num_zones))

    distance_flat = numpy.array(data_packet.distance_mm[0:num_zones])
    distance = numpy.flipud(distance_flat.reshape((grid_size, grid_size)))

    target_status_flat = numpy.array(data_packet.target_status[0:num_zones])
    status_map = numpy.flipud(target_status_flat.reshape((grid_size, grid_size)))
    valid_status_map = numpy.isin(status_map, (STATUS_RANGE_VALID, STATUS_RANGE_VALID_LARGE_PULSE))

    return distance, valid_status_map


def format_array_to_strings(arr, item_format="{: >4d}"): # Ensure 'd' for integers
    lines = []
    rows, cols = arr.shape
    for row_idx in range(rows):
        # Correctly iterate through columns for formatting each element
        formatted_elements_in_row = [item_format.format(arr[row_idx, col_idx]) for col_idx in range(cols)]
        lines.append(" ".join(formatted_elements_in_row))
    return lines


def format_boolean_array_to_strings(arr, true_char='1', false_char='0'):
    lines = []
    rows, cols = arr.shape
    for row_idx in range(rows):
        line = " ".join([(true_char if arr[row_idx, col_idx] else false_char) for col_idx in range(cols)])
        lines.append(line)
    return lines


def print_section_header(title, num_active_sensors):
    full_width = num_active_sensors * COL_WIDTH + (num_active_sensors - 1) * 3
    print(f"\n{title.center(full_width)}\n")


def main():
    args = parse_args()
    sensor_addresses = sorted(list(set(args.tof_addr)))

    print(f"Attempting to use I2C bus: {args.bus if args.bus is not None else '1 (default)'}")
    print(f"Target sensor addresses: {[f'{addr:#02x}' for addr in sensor_addresses]}")

    i2c_bus = None
    if args.bus is not None:
        try:
            i2c_bus = SMBus(args.bus)
            print(f"Successfully opened I2C bus {args.bus}.")
        except Exception as e:
            print(f"Error opening I2C bus {args.bus}: {e}. Will let library use default.")

    sensors = []
    active_sensor_addresses = []
    for addr in sensor_addresses:
        sensor_instance = initialize_sensor(addr, i2c_bus_object=i2c_bus)
        if sensor_instance:
            sensors.append(sensor_instance)
            active_sensor_addresses.append(addr)

    if not sensors:
        print("No sensors initialized. Exiting.")
        if i2c_bus: i2c_bus.close()
        return

    num_active = len(active_sensor_addresses)
    print(f"\n--- Reading data from {num_active} active sensors ---")
    print("Press Ctrl+C to stop.")
    time.sleep(2)

    last_known_distances = [numpy.copy(EMPTY_DISTANCE_MATRIX) for _ in range(num_active)]
    last_known_statuses = [numpy.copy(EMPTY_STATUS_MATRIX) for _ in range(num_active)]
    last_known_obstacle_texts = [EMPTY_OBSTACLE_TEXT for _ in range(num_active)]

    total_header_width = num_active * COL_WIDTH + (num_active - 1) * 3

    try:
        while True:
            clear_terminal()

            header_line_parts = [f"Sensor {active_sensor_addresses[i]:#02x}".center(COL_WIDTH) for i in range(num_active)]
            print("\n" + " | ".join(header_line_parts))
            print("-" * total_header_width)

            for i, sensor in enumerate(sensors):
                if sensor.data_ready():
                    try:
                        data_packet = sensor.get_data()
                        if data_packet:
                            new_dist, new_status = process_sensor_data_for_display(data_packet)
                            last_known_distances[i] = new_dist
                            last_known_statuses[i] = new_status

                            valid_pixels = new_dist[new_status]
                            is_obstacle = numpy.any((valid_pixels < OBSTACLE_THRESHOLD_MM) & (valid_pixels >= 0))
                            last_known_obstacle_texts[i] = str(is_obstacle)
                    except RuntimeError:
                        pass

            print_section_header(f"8x8 Distance Matrix [mm] (Threshold: {OBSTACLE_THRESHOLD_MM}mm)", num_active)
            dist_matrix_str_lines_per_sensor = [format_array_to_strings(dist_matrix) for dist_matrix in last_known_distances]
            for row_idx in range(8):
                row_parts = [dist_matrix_str_lines_per_sensor[s_idx][row_idx].ljust(COL_WIDTH) for s_idx in range(num_active)]
                print(" | ".join(row_parts))

            print_section_header("Obstacle Detected", num_active)
            obstacle_texts_to_print = [text.center(COL_WIDTH) for text in last_known_obstacle_texts]
            print(" | ".join(obstacle_texts_to_print))

            print_section_header("8x8 Ranging Status (1 = Valid)", num_active)
            status_matrix_str_lines_per_sensor = [format_boolean_array_to_strings(status_matrix) for status_matrix in last_known_statuses]
            for row_idx in range(8):
                row_parts = [status_matrix_str_lines_per_sensor[s_idx][row_idx].center(COL_WIDTH) for s_idx in range(num_active)]
                print(" | ".join(row_parts))
            
            print("\n" + "=" * total_header_width)
            print(f"Updating... (Press Ctrl+C to stop) Last update: {time.strftime('%H:%M:%S')}")

            time.sleep(0.05)

    except KeyboardInterrupt:
        clear_terminal()
        print("\nStopping ranging and cleaning up...")
    finally:
        for i, sensor in enumerate(sensors):
            try:
                print(f"Stopping sensor {active_sensor_addresses[i]:#02x}...")
                sensor.stop_ranging()
            except Exception as e:
                print(f"Error stopping sensor {active_sensor_addresses[i]:#02x}: {e}")
        if i2c_bus:
            print("Closing I2C bus...")
            i2c_bus.close()
        print("Done.")

if __name__ == "__main__":
    main()
