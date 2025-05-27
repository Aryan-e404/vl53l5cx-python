# VL53L5CX Multi-Sensor Control Script

## Overview

This script provides a command-line interface to control and visualize data from one or more VL53L5CX Time-of-Flight (ToF) sensors connected through a PCA9546 (or compatible) I2C multiplexer. It allows users to select specific sensors, choose between different output modes, and configure various parameters for sensor operation and display.

Key features include:
*   Support for multiple VL53L5CX sensors via an I2C multiplexer.
*   User-configurable selection of active sensor channels.
*   Dual output modes:
    *   **Text-based terminal output**: Displays 8x8 distance matrices, object detection status, and sensor data validity.
    *   **Curses-based terminal GUI**: Offers a graphical representation of the 8x8 distance grid using colors to indicate distance, alongside object detection status.
*   Configurable I2C addresses for the multiplexer and ToF sensors.
*   Configurable I2C bus number.
*   Adjustable display refresh rate (FPS).
*   Basic object detection ("Object: Yes/No") with distance reporting.

## Hardware Prerequisites

To use this script, you will need the following hardware:
*   **Host System**: A Raspberry Pi (or a similar Linux-based single-board computer) with I2C communication capabilities.
*   **VL53L5CX Time-of-Flight Sensor(s)**: One or more VL53L5CX ToF sensors.
*   **PCA9546 I2C Multiplexer**: A TCA9548A, PCA9546A, or compatible I2C multiplexer to manage communication with multiple sensors (which typically share the same default I2C address).

**Connections:**
1.  Connect each VL53L5CX sensor to a different channel on the I2C multiplexer.
2.  Connect the I2C multiplexer to the I2C bus of your host system (e.g., Raspberry Pi's SDA/SCL pins for I2C bus 1, or other I2C buses if available). Ensure pull-up resistors are appropriately sized and placed if not already present on the modules.
3.  Power all components according to their specifications.

## Software Prerequisites & Installation

1.  **Python 3**: Ensure Python 3 is installed on your host system.
    ```bash
    sudo apt-get update
    sudo apt-get install python3 python3-pip
    ```

2.  **Enable I2C Interface**: On a Raspberry Pi, enable the I2C interface:
    *   Run `sudo raspi-config`.
    *   Navigate to `Interface Options` -> `I2C`.
    *   Select `Yes` to enable the I2C interface.
    *   Reboot if prompted.
    *   You may also need to install I2C tools: `sudo apt-get install i2c-tools`. Use `i2cdetect -y <bus_num>` (e.g., `i2cdetect -y 1`) to check connected devices.

3.  **Install Required Python Libraries**:
    *   **`vl53l5cx-ctypes` and `smbus2`**: The `vl53l5cx-ctypes` library is used for interfacing with the sensors. `smbus2` is required for I2C communication on Linux systems and is typically installed as a dependency of `vl53l5cx-ctypes`.
        ```bash
        pip3 install vl53l5cx-ctypes
        ```
    *   **`numpy`**: Used for numerical operations, particularly for handling the 8x8 data arrays from the sensors.
        ```bash
        pip3 install numpy
        ```

## Usage

The script is run from the command line using Python 3.

Basic command structure:
```bash
python3 tof_control.py --sensors <idx1> [<idx2> ...] [options]
```

**Command-Line Arguments:**

*   `--sensors SENSORS [SENSORS ...]`
    *   **Required.**
    *   A list of one or more sensor indices (mux channels) to activate. Indices are typically 0-3 for a PCA9546 (4-channel) or 0-7 for a PCA9548 (8-channel).
    *   Example: `--sensors 0` or `--sensors 0 1 3`

*   `--gui`
    *   Optional.
    *   Enable the curses-based graphical user interface in the terminal.

*   `--text_output`
    *   Optional.
    *   Enable text-based output in the terminal.
    *   If neither `--gui` nor `--text_output` is specified, `--text_output` is enabled by default.

*   `--mux_address MUX_ADDRESS`
    *   Optional.
    *   The I2C address of the I2C multiplexer.
    *   Default: `0x70`.
    *   Address can be specified in hex (e.g., `0x70`) or decimal.

*   `--tof_address TOF_ADDRESS`
    *   Optional.
    *   The I2C address of the VL53L5CX ToF sensors. This is relevant if the sensors' default address (0x29) has been changed. This script assumes all sensors use the same I2C address (managed by the multiplexer).
    *   Default: `0x29`.
    *   Address can be specified in hex (e.g., `0x29`) or decimal.

*   `--i2c_bus_num I2C_BUS_NUM`
    *   Optional.
    *   The I2C bus number to use (e.g., 1 for `/dev/i2c-1`, 4 for `/dev/i2c-4`).
    *   Default: `1`.

*   `--fps FPS`
    *   Optional.
    *   Target frames per second for display refresh.
    *   Default: `10.0`.
    *   Note: For optimal performance and to avoid displaying duplicate frames, this value should ideally be less than or equal to the ranging frequency configured on the sensors (typically 10-15 Hz by default for VL53L5CX).

## Examples

1.  **Run with two sensors (channels 0 and 1) and display text output:**
    ```bash
    python3 tof_control.py --sensors 0 1 --text_output
    ```
    (Since `--text_output` is the default if no output mode is specified, you can also use: `python3 tof_control.py --sensors 0 1`)

2.  **Run with one sensor (channel 0), display GUI output, at 5 FPS:**
    ```bash
    python3 tof_control.py --sensors 0 --gui --fps 5
    ```

3.  **Run with sensors on channels 2 and 3, specifying a non-default multiplexer address (0x71):**
    ```bash
    python3 tof_control.py --sensors 2 3 --mux_address 0x71
    ```

4.  **Run with sensors on channels 0 and 1, using I2C bus number 4:**
    ```bash
    python3 tof_control.py --sensors 0 1 --i2c_bus_num 4
    ```

## Output Description

### Text Output (`--text_output`)

When text output is enabled:
*   The terminal screen is cleared on each update.
*   Data for each selected sensor is displayed in a separate block, arranged horizontally.
*   Each sensor block includes:
    *   **Sensor Index Header**: e.g., "--- Sensor 0 ---".
    *   **Distance Matrix**: An 8x8 grid of distance values in millimeters.
    *   **Object Detection**: A message indicating if an object is detected within a predefined threshold (currently 1000mm), e.g., "Object: Yes (at 350 mm)" or "Object: No". If an object is detected but is further than the threshold, it might show "Object: No (nearest YYY mm)".
    *   **Status Matrix**: An 8x8 grid where '1' indicates a valid sensor reading for that cell and '0' indicates an invalid reading.

### GUI Output (`--gui`)

When GUI output is enabled (uses `curses`):
*   The terminal is transformed into a full-screen interface.
*   The screen is divided into vertical panels, one for each selected sensor.
*   Each sensor panel displays:
    *   **Sensor Index Title**: e.g., "Sensor X".
    *   **Graphical 8x8 Grid**:
        *   Each cell of the 8x8 sensor data is represented by a block character (e.g., "██").
        *   The color of the block indicates the measured distance:
            *   **Red**: Close distance (e.g., 0-500mm).
            *   **Yellow**: Medium-close distance (e.g., 501-1000mm).
            *   **Cyan**: Medium-far distance (e.g., 1001-2000mm).
            *   **Green**: Far distance (e.g., >2000mm).
        *   Cells with invalid status or zero distance are typically shown as a dim character (e.g., ". ").
    *   **Object Detection Message**: Similar to the text output, a message like "Object: Yes (at 350 mm)" is displayed below the grid.
*   The GUI updates at the rate specified by `--fps`.
*   Press `Ctrl+C` to exit the GUI and the script.
