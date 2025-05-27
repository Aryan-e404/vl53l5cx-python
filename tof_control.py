#!/usr/bin/env python3
"""
tof_control.py - Control and visualize data from VL53L5CX Time-of-Flight sensors.

This script interfaces with one or more VL53L5CX ToF sensors connected via a
PCA9546 (or compatible) I2C multiplexer. It supports displaying sensor data in
two modes:
1.  Text-based output: Shows 8x8 distance matrices, object detection status,
    and validity status for selected sensors, arranged horizontally in the terminal.
2.  Curses-based GUI: Provides a graphical representation of the 8x8 distance
    grid for each sensor, using colors to indicate distance and characters to
    show cell validity. Also displays object detection status.

Key Features:
-   Supports multiple VL53L5CX sensors via an I2C multiplexer.
-   User-selectable sensors to activate.
-   Dual output modes: text and curses-based GUI.
-   Configurable I2C addresses for multiplexer and sensors.
-   Configurable display refresh rate (FPS).
-   Graceful handling of sensor errors and I2C communication issues.
-   Automatic flipping of sensor data (np.flipud) to match common physical orientation.

Usage:
    ./tof_control.py --sensors <idx1> [<idx2> ...] [--gui | --text_output] [options]

Example:
    ./tof_control.py --sensors 0 1 --gui --fps 15
    ./tof_control.py --sensors 2 --text_output --mux_address 0x71
"""

import argparse
import smbus2
import numpy as np
import time
import vl53l5cx_ctypes
from vl53l5cx_ctypes import RESOLUTION_8X8 # Assuming this might be needed early
import sys
import os # For clearing screen
import curses # For GUI output

DEFAULT_MUX_ADDRESS = 0x70 # Standard address for PCA9546/PCA9548 multiplexers

def select_channel(bus, mux_address, channel):
    """
    Selects a channel on the I2C multiplexer (e.g., PCA9546).

    Args:
        bus: Initialized smbus2.SMBus object.
        mux_address: The I2C address of the multiplexer.
        channel: The integer channel number to select (e.g., 0, 1, 2, 3).

    Returns:
        True if the channel selection command was sent successfully, False otherwise.
    """
    # PCA9546 is a 4-channel multiplexer, channels 0-3.
    # Some PCA9548 variants have 8 channels. For now, assume 0-3.
    # If using an 8-channel mux, change max_channel to 7.
    max_channel = 3 
    if not (0 <= channel <= max_channel):
        print(f"Error: Channel number {channel} is out of range (0-{max_channel}).")
        return False

    control_byte = 1 << channel
    
    try:
        bus.write_byte(mux_address, control_byte)
        return True
    except OSError as e:
        print(f"Error: Failed to write to I2C multiplexer at 0x{mux_address:02x} on channel {channel}.")
        print(f"  Details: {e}")
        return False

def parse_arguments():
    """Parses command-line arguments for the ToF sensor control script."""
    parser = argparse.ArgumentParser(description="Control VL53L5CX ToF sensors via a PCA9546 I2C multiplexer.")

    # Sensor selection
    parser.add_argument('--sensors', nargs='+', type=int, required=True,
                        help='List of sensor indices to activate (e.g., 0 1 2). Max index 3 for PCA9546.')

    # Output mode
    parser.add_argument('--gui', action='store_true',
                        help='Enable GUI output mode.')
    parser.add_argument('--text_output', action='store_true',
                        help='Enable text-based 8x8 matrix output mode.')

    # I2C Addresses
    parser.add_argument('--mux_address', type=lambda x: int(x, 0), default=DEFAULT_MUX_ADDRESS,
                        help=f'I2C address of the PCA9546 multiplexer (default: {DEFAULT_MUX_ADDRESS:#04x}). Allows hex (e.g. 0x70) or decimal.')
    parser.add_argument('--tof_address', type=lambda x: int(x, 0), default=vl53l5cx_ctypes.DEFAULT_I2C_ADDRESS,
                        help=f'I2C address of the ToF sensors (default: {vl53l5cx_ctypes.DEFAULT_I2C_ADDRESS:#04x}). Allows hex (e.g. 0x29) or decimal.')
    
    # I2C Bus Number
    parser.add_argument('--i2c_bus_num', type=int, default=1,
                        help='The I2C bus number (e.g., 1 for /dev/i2c-1, 4 for /dev/i2c-4). Default: 1.')

    # Display refresh rate
    parser.add_argument('--fps', type=float, default=10.0,
                        help='Target frames per second for display refresh (e.g., 10.0). Default: 10.0.')

    args = parser.parse_args()

    # Validate sensor indices
    # Assuming max_channel = 3 (for PCA9546 with 4 channels 0,1,2,3)
    # This could be made more flexible, e.g. by an argument or a global constant.
    max_sensor_index = 3 
    for sensor_idx in args.sensors:
        if not (0 <= sensor_idx <= max_sensor_index):
            parser.error(f"Sensor index {sensor_idx} is out of the valid range (0-{max_sensor_index}).")

    # Validate FPS
    if args.fps <= 0:
        parser.error("FPS must be a positive value.")

    # Default output mode logic
    if not args.gui and not args.text_output:
        print("No output mode specified. Defaulting to text output.")
        args.text_output = True
    
    # Future: could add a check for mutually exclusive GUI/Text if that's desired.
    # For now, both can be true, and the main loop can decide how to handle it.

    return args

def initialize_sensors(args):
    """
    Initializes the VL53L5CX ToF sensors connected via an I2C multiplexer.

    Args:
        args: Parsed command-line arguments.

    Returns:
        A dictionary mapping sensor_index to the initialized VL53L5CX sensor object.
        Exits the script if no sensors can be initialized or if the I2C bus fails.
    """
    print("Initializing sensors... This may take a moment.")
    active_sensors = {}
    bus = None # Define bus here to ensure it's in scope for a potential finally block if needed

    try:
        bus = smbus2.SMBus(args.i2c_bus_num)
        print(f"Successfully opened I2C bus /dev/i2c-{args.i2c_bus_num}.")
    except (FileNotFoundError, PermissionError) as e:
        print(f"Error: Failed to open I2C bus /dev/i2c-{args.i2c_bus_num}. {e}")
        print("Please ensure the I2C interface is enabled and you have permissions, and that the bus number is correct.")
        sys.exit(1)
    except Exception as e: # Catch other smbus2 related errors
        print(f"Error: An unexpected error occurred while opening I2C bus /dev/i2c-{args.i2c_bus_num}. {e}")
        sys.exit(1)

    for sensor_index in args.sensors:
        print(f"\nAttempting to initialize sensor on mux channel {sensor_index}...")
        
        if not select_channel(bus, args.mux_address, sensor_index):
            print(f"Error: Could not select mux channel {sensor_index} at address {args.mux_address:#02x}. Skipping this sensor.")
            continue

        try:
            print(f"  Instantiating VL53L5CX sensor at I2C address {args.tof_address:#02x} on channel {sensor_index}...")
            # The VL53L5CX library expects the bus object directly.
            # The library handles the firmware upload during __init__ (which calls init_sensor).
            tof = vl53l5cx_ctypes.VL53L5CX(i2c_dev=bus, i2c_addr=args.tof_address)
            
            print(f"  Setting resolution to 8x8 for sensor on channel {sensor_index}...")
            tof.set_resolution(vl53l5cx_ctypes.RESOLUTION_8X8)
            
            print(f"  Starting ranging for sensor on channel {sensor_index}...")
            tof.start_ranging()
            
            active_sensors[sensor_index] = tof
            print(f"Successfully initialized sensor on mux channel {sensor_index}.")

        except vl53l5cx_ctypes.VL53L5CXError as e: # Catch specific library errors
            print(f"Error: Failed to initialize VL53L5CX sensor on channel {sensor_index} at address {args.tof_address:#02x}.")
            print(f"  Details: {e}")
            print(f"  This could be due to incorrect I2C address, sensor not connected, or firmware issues.")
        except OSError as e: # Catch I2C communication errors during sensor init
            print(f"Error: I2C communication failed with sensor on channel {sensor_index} at address {args.tof_address:#02x}.")
            print(f"  Details: {e}")
        except Exception as e: # Catch any other unexpected errors
            print(f"Error: An unexpected error occurred while initializing sensor on channel {sensor_index}.")
            print(f"  Details: {e}")

    if not active_sensors:
        print("\nError: No sensors were successfully initialized. Exiting.")
        if bus:
             bus.close()
        sys.exit(1)

    print(f"\nInitialized {len(active_sensors)} sensor(s): {list(active_sensors.keys())}")
    # The bus should remain open for the sensors to communicate.
    # It will be closed by the main function's finally block.
    return active_sensors, bus

def display_text_output(sensor_data_map, args):
    """Displays sensor data as text.
    sensor_data_map is a dictionary: {sensor_idx: {'distance': array, 'status': array}}
    or sensor_idx: None if data retrieval failed for that sensor.
    """
    # 1. Clear the terminal screen
    print("\033c", end="") # ANSI escape sequence for clearing screen

    if not args.sensors:
        print("No sensors specified for display.")
        return

    if not sensor_data_map and any(idx is not None for idx in args.sensors):
        # This case means args.sensors has entries, but sensor_data_map is empty.
        # This could happen if all sensors failed very early.
        print("No data available from any sensor.")
        # Fall through to print headers and N/A for each specified sensor
        
    sensor_display_blocks = []
    all_sensor_headers = []

    # Define a fixed width for each sensor's display block for easier alignment
    # This needs to accommodate the 8x8 matrix (8 * 5 chars + spaces) and headers.
    # Approx 8 * 5 (nums) + 7 * 1 (spaces) = 47 chars for matrix. Add header/status.
    # Let's estimate block_width.
    # An 8x8 matrix formatted with 4-digit numbers + space is `8*5 - 1 = 39` chars wide.
    # Let's set a nominal width for formatting.
    block_width = 45 # characters per sensor block

    for sensor_idx in args.sensors:
        all_sensor_headers.append(f"Sensor {sensor_idx}".center(block_width))
        
        sensor_lines = []
        data = sensor_data_map.get(sensor_idx)

        if data is None or 'distance' not in data or data['distance'] is None:
            sensor_lines.append("  Distance (mm):".ljust(block_width))
            no_data_msg = "N/A".center(block_width)
            for _ in range(8): # 8 lines for matrix placeholder
                sensor_lines.append(no_data_msg)
            sensor_lines.append("".ljust(block_width)) # Spacer line
            sensor_lines.append("  Object Detected: N/A".ljust(block_width))
            sensor_lines.append("".ljust(block_width)) # Spacer line
            sensor_lines.append("  Status (Valid=1):".ljust(block_width))
            for _ in range(8): # 8 lines for matrix placeholder
                sensor_lines.append(no_data_msg)
        else:
            # Distance Matrix
            sensor_lines.append("  Distance (mm):".ljust(block_width))
            dist_matrix_str = np.array2string(
                data['distance'],
                formatter={'float_kind': lambda x: "%4d" % x, 'int': lambda x: "%4d" % x},
                separator=' ',
                threshold=np.inf # print full matrix
            )
            # Remove brackets and align
            for line in dist_matrix_str.replace('[', ' ').replace(']', ' ').strip().split('\n'):
                sensor_lines.append(f"  {line.strip()}".ljust(block_width))

            sensor_lines.append("".ljust(block_width)) # Spacer line

            # Object Detection
            min_dist_val = np.inf
            valid_distances = data['distance'][data['distance'] > 0]
            if valid_distances.size > 0:
                min_dist_val = np.min(valid_distances)
            
            # Using 1000mm as an example threshold for "close object"
            if 0 < min_dist_val < 1000: 
                obj_msg = f"  Object: Yes (at {int(min_dist_val)} mm)"
            else:
                obj_msg = "  Object: No"
            sensor_lines.append(obj_msg.ljust(block_width))
            sensor_lines.append("".ljust(block_width)) # Spacer line

            # Status Matrix
            sensor_lines.append("  Status (Valid=1):".ljust(block_width))
            status_matrix_str = np.array2string(
                data['status'].astype(int), # Convert boolean to int for 0/1 output
                formatter={'int': lambda x: "%1d" % x},
                separator=' ',
                threshold=np.inf
            )
            # Remove brackets and align
            for line in status_matrix_str.replace('[', ' ').replace(']', ' ').strip().split('\n'):
                sensor_lines.append(f"    {line.strip()}".ljust(block_width)) # Extra indent for status

        sensor_display_blocks.append(sensor_lines)

    # Print headers horizontally
    print(" | ".join(all_sensor_headers))
    print("-" * (len(all_sensor_headers) * (block_width + 3) - 3)) # Separator line

    # Determine max number of lines for vertical alignment
    max_lines = 0
    if sensor_display_blocks:
        max_lines = max(len(block) for block in sensor_display_blocks)

    # Pad blocks to have the same number of lines
    for block in sensor_display_blocks:
        while len(block) < max_lines:
            block.append("".ljust(block_width)) # Pad with empty lines of fixed width

    # Print content lines horizontally
    for i in range(max_lines):
        line_parts = [block[i] for block in sensor_display_blocks]
        print(" | ".join(line_parts))

def display_gui_output(sensor_data_map, args):
    """Wraps the curses GUI to handle setup and cleanup.
    sensor_data_map is a dictionary: {sensor_idx: {'distance': array, 'status': array}}
    or sensor_idx: None if data retrieval failed for that sensor.
    """
    try:
        # curses.wrapper handles terminal setup and cleanup
        curses.wrapper(curses_gui_wrapper, sensor_data_map, args)
    except curses.error as e:
        # Don't print if it's just about getch failing due to no input on non-blocking mode
        if "no input" not in str(e).lower():
            print(f"Curses error: {e}")
            print("If the terminal is messed up, try typing 'reset'.")
    except Exception as e:
        # Catch other potential errors to prevent script crash
        print(f"An unexpected error occurred in GUI display: {e}")

def curses_gui_wrapper(stdscr, sensor_data_map, args):
    """
    Handles the actual curses-based GUI drawing.
    This function is called by curses.wrapper.
    stdscr: The main window object provided by curses.
    sensor_data_map: Data for all sensors.
    args: Command-line arguments.
    """
    OBJECT_DETECT_THRESHOLD_MM = 1000 # Threshold for "close object" detection

    # Basic curses setup
    stdscr.nodelay(True)  # Non-blocking getch() for stdscr (mainly for responsiveness)
    curses.curs_set(0)    # Hide the cursor
    
    CELL_CHAR = "██"  # Represents one data cell, 2 terminal characters wide
    INVALID_CELL_CHAR = ". " # For invalid cells, also 2 terminal characters wide

    col_attr = {} # To store color attributes

    if curses.has_colors():
        curses.start_color()
        # Define color pairs: (pair_number, foreground_color, background_color)
        curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)    # 0-500mm (Close)
        curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK) # 501-1000mm (Medium-Close)
        curses.init_pair(3, curses.COLOR_CYAN, curses.COLOR_BLACK)   # 1001-2000mm (Medium-Far)
        curses.init_pair(4, curses.COLOR_GREEN, curses.COLOR_BLACK)  # >2000mm (Far)
        curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLACK)  # Default text, Titles, Borders
        curses.init_pair(6, curses.COLOR_WHITE, curses.COLOR_BLACK)  # Base for Invalid/No reading cells
        
        col_attr['close'] = curses.color_pair(1)
        col_attr['medium_close'] = curses.color_pair(2)
        col_attr['medium_far'] = curses.color_pair(3)
        col_attr['far'] = curses.color_pair(4)
        col_attr['text'] = curses.color_pair(5)
        col_attr['title'] = curses.color_pair(5) | curses.A_BOLD
        col_attr['border'] = curses.color_pair(5)
        col_attr['invalid'] = curses.color_pair(6) 
        col_attr['placeholder_text'] = curses.color_pair(5)
    else: # Fallback for no colors - all attributes are 0 (normal)
        for attr_name in ['close', 'medium_close', 'medium_far', 'far', 'text', 'title', 'border', 'invalid', 'placeholder_text']:
            col_attr[attr_name] = 0 # Use 'attr_name' for clarity

    # Attempt to read a key to see if the terminal is responsive / handle Ctrl+C via KeyboardInterrupt
    try:
        key = stdscr.getch() # Check for input, e.g., to catch Ctrl+C if terminal sends it as a key
        if key == 3: # ASCII for ETX (End of Text), often sent by Ctrl+C
            raise KeyboardInterrupt
    except curses.error: # 'no input' is expected if nodelay(True)
        pass
    # stdscr.clear() is implicitly handled by curses.wrapper on the first call.
    # Subsequent calls to curses_gui_wrapper will manage clearing via sensor_win.erase().

    height, width = stdscr.getmaxyx()

    if not args.sensors:
        if height > 0 and width > 0:
             stdscr.addstr(0, 0, "No sensors specified for GUI display.", col_attr.get('text', 0))
             stdscr.refresh()
        return

    num_sensors = len(args.sensors)
    if num_sensors == 0:
        if height > 0 and width > 0:
            stdscr.addstr(0,0, "Zero sensors to display.", col_attr.get('text', 0))
            stdscr.refresh()
        return
        
    sensor_window_width = width // num_sensors
    max_sensor_display_height = height 

    for i, sensor_idx in enumerate(args.sensors):
        start_x = i * sensor_window_width
        current_sensor_width = sensor_window_width
        if i == num_sensors - 1: # Last sensor takes all remaining width
            current_sensor_width = width - start_x
        
        # Ensure window dimensions are valid
        if max_sensor_display_height <= 0 or current_sensor_width <= 0:
            continue # Skip if window size is invalid (e.g. terminal too small)

        try:
            sensor_win = curses.newwin(max_sensor_display_height, current_sensor_width, 0, start_x)
            sensor_win.erase() # Clear previous content of this subwindow for this tick

            # Redraw border and title
            sensor_win.border(0,0,0,0,0,0,0,0, col_attr.get('border',0))
            title = f"Sensor {sensor_idx}"
            title_x = (current_sensor_width - len(title)) // 2
            if title_x < 1 : title_x = 1 # Ensure title is not on the border
            if 1 < max_sensor_display_height -1 : # Check if space for title
                 sensor_win.addstr(1, title_x, title, col_attr.get('title',0))
            
            current_data = sensor_data_map.get(sensor_idx)

            top_offset = 3  # Start drawing grid below title line and a small buffer
            left_offset = 2 # Padding from left border for the grid

            if current_data and \
               isinstance(current_data.get('distance'), np.ndarray) and \
               isinstance(current_data.get('status'), np.ndarray) and \
               current_data['distance'].shape == (8,8) and \
               current_data['status'].shape == (8,8):

                distance_array = current_data['distance']
                status_array = current_data['status']
                
                required_grid_height = 8 # 8 rows
                required_grid_width = 8 * len(CELL_CHAR) # 8 cells, each CELL_CHAR wide

                if (max_sensor_display_height - top_offset - 1) < required_grid_height or \
                   (current_sensor_width - left_offset - 1) < required_grid_width:
                    msg = "Win too small for 8x8 grid"
                    msg_y = top_offset + required_grid_height // 2
                    msg_x = max(1, (current_sensor_width - len(msg)) // 2)
                    if msg_y < max_sensor_display_height -1 and msg_x > 0:
                         sensor_win.addstr(msg_y, msg_x, msg, col_attr.get('text',0))
                else:
                    for r in range(8): # 8 rows
                        for c in range(8): # 8 columns
                            distance_val = distance_array[r, c]
                            is_valid = status_array[r, c]
                            
                            char_to_display = CELL_CHAR
                            color_attribute_val = col_attr.get('invalid',0) 

                            if is_valid and distance_val > 0:
                                if distance_val <= 500:
                                    color_attribute_val = col_attr.get('close',0)
                                elif distance_val <= 1000:
                                    color_attribute_val = col_attr.get('medium_close',0)
                                elif distance_val <= 2000:
                                    color_attribute_val = col_attr.get('medium_far',0)
                                else: # > 2000
                                    color_attribute_val = col_attr.get('far',0)
                            else: # Invalid or distance <= 0
                                char_to_display = INVALID_CELL_CHAR
                                color_attribute_val = col_attr.get('invalid',0)
                                if curses.has_colors(): 
                                     color_attribute_val |= curses.A_DIM
                            
                            draw_y = top_offset + r
                            draw_x = left_offset + c * len(CELL_CHAR) # CELL_CHAR is 2 chars wide
                            
                            if draw_y < (max_sensor_display_height - 1) and \
                               (draw_x + len(char_to_display) -1) < (current_sensor_width - 1):
                                try:
                                    sensor_win.addstr(draw_y, draw_x, char_to_display, color_attribute_val)
                                except curses.error:
                                    pass # Skip if addstr fails (e.g. drawing at bottom-right corner char)
            else:
                # Data is None or malformed for this sensor
                placeholder_text = "Data: N/A"
                placeholder_y = max_sensor_display_height // 2
                placeholder_x = (current_sensor_width - len(placeholder_text)) // 2
                if placeholder_y > 1 and placeholder_x > 0 and \
                   placeholder_y < max_sensor_display_height -1 and \
                   (placeholder_x + len(placeholder_text)) < current_sensor_width -1:
                     sensor_win.addstr(placeholder_y, placeholder_x, placeholder_text, col_attr.get('placeholder_text',0))

            # Display Object Detection Status
            obj_message = "Object: N/A"
            obj_message_y_pos = top_offset + 8 + 1 # 1 line below the 8-row grid
            obj_message_x_pos = left_offset

            if current_data and \
               isinstance(current_data.get('distance'), np.ndarray) and \
               isinstance(current_data.get('status'), np.ndarray):
                
                distance_array = current_data['distance']
                status_array = current_data['status']
                min_valid_distance = np.inf

                for r_obj in range(8):
                    for c_obj in range(8):
                        if status_array[r_obj, c_obj] and distance_array[r_obj, c_obj] > 0:
                            min_valid_distance = min(min_valid_distance, distance_array[r_obj, c_obj])
                
                if min_valid_distance != np.inf :
                    if min_valid_distance < OBJECT_DETECT_THRESHOLD_MM:
                        obj_message = f"Object: Yes (at {int(min_valid_distance)} mm)"
                    else: # Object detected but further than threshold
                        obj_message = f"Object: No (nearest {int(min_valid_distance)} mm)"
                else: # No valid target found
                    obj_message = "Object: No"

            # Clear the line before writing new message
            if obj_message_y_pos < max_sensor_display_height - 1: # Ensure y is within bounds
                sensor_win.move(obj_message_y_pos, obj_message_x_pos)
                sensor_win.clrtoeol() # Clear from cursor to end of line
                
                # Check if message fits
                if (obj_message_x_pos + len(obj_message)) < current_sensor_width -1:
                    try:
                        sensor_win.addstr(obj_message_y_pos, obj_message_x_pos, obj_message, col_attr.get('text', 0))
                    except curses.error:
                        pass # Avoid crash if addstr fails at edge

            sensor_win.refresh()

        except curses.error as e:
            # Handle errors specific to this sensor's window (e.g., if terminal resized too small suddenly)
            # This is a fallback; robust resize handling is more complex.
            # For now, we just ensure the main loop doesn't crash.
            if i == num_sensors - 1 and stdscr: # Try to report on stdscr if it's the last window
                stdscr.clear()
                stdscr.addstr(0,0, f"Error in sensor window {sensor_idx}: {e}", col_attr.get('text',0))
                stdscr.refresh()
            pass # Continue to next sensor window or next tick
        except Exception as e: # Catch other unexpected errors
             if i == num_sensors - 1 and stdscr:
                stdscr.clear()
                stdscr.addstr(0,0, f"Unexpected GUI error for sensor {sensor_idx}: {e}", col_attr.get('text',0))
                stdscr.refresh()
             pass

    # stdscr.refresh() is not strictly needed here because all content is drawn into 
    # sub-windows (sensor_win), which are individually refreshed.

def main():
    """Main function to control the ToF sensor data acquisition and display."""
    args = parse_arguments()
    
    active_sensors, bus = initialize_sensors(args) # initialize_sensors now returns bus

    if not active_sensors or not bus:
        # This case should ideally be handled by initialize_sensors exiting,
        # but as a safeguard:
        print("Critical error: Sensors or I2C bus not initialized. Exiting.")
        if bus:
            bus.close()
        sys.exit(1)

    try:
        print("\nStarting data acquisition loop... Press Ctrl+C to exit.")
        while True:
            current_sensor_data = {} # Data for all sensors for this tick

            for sensor_idx in args.sensors: # Iterate in user-specified order
                if sensor_idx not in active_sensors:
                    # This should not happen if initialize_sensors is correct and args.sensors is validated
                    print(f"Warning: Sensor index {sensor_idx} requested but not found in active sensors. Skipping.")
                    continue

                tof_sensor = active_sensors[sensor_idx]
                
                if not select_channel(bus, args.mux_address, sensor_idx):
                    print(f"Error: Failed to select mux channel {sensor_idx} in main loop. Skipping sensor for this tick.")
                    # Optionally store error state for this sensor_idx in current_sensor_data
                    current_sensor_data[sensor_idx] = None 
                    continue
                
                try:
                    if tof_sensor.check_data_ready():
                        ranging_data = tof_sensor.get_ranging_data()
                        
                        if ranging_data and ranging_data.distance_mm and ranging_data.target_status:
                            num_pixels = tof_sensor.get_resolution() # e.g., 64 for 8x8
                            side = int(np.sqrt(num_pixels))
                            
                            # Process distance data
                            distance_array = np.array(ranging_data.distance_mm).reshape((side, side))
                            distance_array = np.flipud(distance_array) # Flip UD as per common examples
                            
                            # Process target status data
                            # Valid statuses: 5 (VALID_RANGE), 9 (VALID_RANGE_LARGE_PULSE)
                            # Other statuses (e.g. 0-4, 6-8) are typically not 'good' targets
                            valid_statuses = (
                                vl53l5cx_ctypes.STATUS_RANGE_VALID, 
                                vl53l5cx_ctypes.STATUS_RANGE_VALID_LARGE_PULSE
                            )
                            status_raw = np.array(ranging_data.target_status).reshape((side, side))
                            status_array = np.isin(status_raw, valid_statuses)
                            status_array = np.flipud(status_array) # Flip UD to match distance

                            current_sensor_data[sensor_idx] = {
                                'distance': distance_array,
                                'status': status_array
                            }
                            # print(f"Sensor {sensor_idx}: Data acquired.") # Can be too verbose
                        else:
                            # Ranging data object exists, but no actual distance_mm or target_status
                            print(f"Sensor {sensor_idx}: Data ready, but ranging_data content is missing/empty.")
                            current_sensor_data[sensor_idx] = None # Indicate data retrieval issue
                    else:
                        # Data not ready for sensor_idx
                        # print(f"Sensor {sensor_idx}: Data not ready.") # Can be verbose
                        # Not adding to current_sensor_data or current_sensor_data[sensor_idx] = None
                        # This means display functions will show "not available" or skip.
                        current_sensor_data[sensor_idx] = None # Explicitly mark as not ready this tick

                except (vl53l5cx_ctypes.VL53L5CXError, IOError) as e: # Added IOError
                    print(f"Error reading data from sensor {sensor_idx}: {e}")
                    current_sensor_data[sensor_idx] = None # Indicate error
                except Exception as e:
                    print(f"Unexpected error processing sensor {sensor_idx}: {e}")
                    current_sensor_data[sensor_idx] = None # Indicate error

            # After iterating through all sensors for the current tick:
            if args.text_output:
                display_text_output(current_sensor_data, args)
            if args.gui:
                display_gui_output(current_sensor_data, args)
            
            # Calculate sleep duration based on target FPS
            # Note: The actual sensor ranging frequency might be different.
            # For best results, FPS should generally be <= the sensor's ranging frequency.
            # Default sensor ranging frequency is often 10-15Hz if not reconfigured.
            sleep_duration = 1.0 / args.fps
            time.sleep(sleep_duration)

    except KeyboardInterrupt:
        print("\nCtrl+C detected. Exiting program gracefully.")
    finally:
        print("Cleaning up resources...")
        if bus: # Ensure bus was successfully created before trying to use/close
            # Stop ranging on all initialized sensors
            print("Stopping ranging on active sensors...")
            for sensor_idx, tof_sensor in active_sensors.items():
                try:
                    # Select channel before stopping, as stop_ranging() communicates with the sensor
                    if not select_channel(bus, args.mux_address, sensor_idx):
                         print(f"Warning: Could not select channel {sensor_idx} to stop ranging. Sensor may not stop correctly.")
                    print(f"  Stopping ranging for sensor {sensor_idx}...")
                    tof_sensor.stop_ranging()
                except Exception as e:
                    print(f"  Error stopping sensor {sensor_idx}: {e}")
            
            bus.close()
            print("I2C bus closed.")
        else:
            print("I2C bus was not initialized, no bus to close.")
        print("Cleanup complete.")

if __name__ == "__main__":
    main()
