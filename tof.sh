#!/bin/bash

# Configuration
I2C_BUS="4"
MUX_ADDRESS="0x70"
DEFAULT_SENSOR_ADDRESS="0x29"
PYTHON_SCRIPT="/home/root/vl53l5cx-python/examples/change_i2c_address.py"
LOG_FILE="sensor_setup_$(date +%Y%m%d_%H%M%S).log"
SCRIPT_NAME=$(basename "$0")

# Arrays for channel and address mapping
# MUX_CHANNEL_VALUES are the values sent to the MUX to select a channel
# DESIRED_SENSOR_ADDRESSES are the new I2C addresses for the sensors
MUX_CHANNEL_VALUES=(0x01 0x02 0x04 0x08)
DESIRED_SENSOR_ADDRESSES=(0x20 0x21 0x22 0x23)
# For user-friendly logging, map MUX_CHANNEL_VALUES to logical channel numbers
LOGICAL_CHANNELS=(1 2 3 4)

# --- Helper Function for Logging ---
log_message() {
    local type="$1" # INFO, ERROR, SUCCESS
    local message="$2"
    echo "$(date '+%Y-%m-%d %H:%M:%S') - [${SCRIPT_NAME}] - [${type}] - ${message}" | tee -a "${LOG_FILE}"
}

# --- Pre-flight Checks ---
log_message "INFO" "Starting sensor I2C address configuration script."

if ! command -v i2cset &> /dev/null; then
    log_message "ERROR" "i2cset command not found. Please install i2c-tools."
    exit 1
fi
log_message "INFO" "i2cset command found."

if ! command -v i2cdetect &> /dev/null; then
    log_message "ERROR" "i2cdetect command not found. Please install i2c-tools."
    exit 1
fi
log_message "INFO" "i2cdetect command found."


if [ ! -f "$PYTHON_SCRIPT" ]; then
    log_message "ERROR" "Python script not found at ${PYTHON_SCRIPT}."
    exit 1
fi
log_message "INFO" "Python script found at ${PYTHON_SCRIPT}."

if ! command -v python3 &> /dev/null; then
    log_message "ERROR" "python3 command not found. Please install Python 3."
    exit 1
fi
log_message "INFO" "python3 command found."

# --- Main Logic ---
all_sensors_configured_successfully=true
final_script_exit_code=0 # Assume success initially

# Disable all channels on the MUX first to avoid conflicts (write 0x00)
log_message "INFO" "Disabling all MUX channels (writing 0x00 to MUX ${MUX_ADDRESS} on bus ${I2C_BUS})."
i2cset -y "${I2C_BUS}" "${MUX_ADDRESS}" 0x00
if [ $? -ne 0 ]; then
    log_message "ERROR" "Failed to disable MUX channels. This might cause issues. Continuing cautiously."
    # Depending on severity, you might want to exit here or set a flag
else
    log_message "SUCCESS" "Successfully disabled all MUX channels."
fi
sleep 0.1 # Small delay after MUX operations

num_channels=${#MUX_CHANNEL_VALUES[@]}

for (( i=0; i<${num_channels}; i++ )); do
    mux_channel_value="${MUX_CHANNEL_VALUES[$i]}"
    desired_address="${DESIRED_SENSOR_ADDRESSES[$i]}"
    logical_channel="${LOGICAL_CHANNELS[$i]}"

    log_message "INFO" "------------------------------------------------------------"
    log_message "INFO" "Processing Logical Channel ${logical_channel} (MUX value: ${mux_channel_value}, Target Address: ${desired_address})"

    # 1. Select the channel on the I2C MUX
    log_message "INFO" "Selecting MUX channel ${logical_channel} (writing ${mux_channel_value} to MUX ${MUX_ADDRESS} on bus ${I2C_BUS})."
    i2cset_output=$(i2cset -y "${I2C_BUS}" "${MUX_ADDRESS}" "${mux_channel_value}" 2>&1)
    if [ $? -ne 0 ]; then
        log_message "ERROR" "Failed to select MUX channel ${logical_channel} (value ${mux_channel_value}). Output: ${i2cset_output}"
        log_message "ERROR" "Skipping sensor on channel ${logical_channel}."
        all_sensors_configured_successfully=false
        final_script_exit_code=1
        continue # Move to the next sensor
    else
        log_message "SUCCESS" "Successfully selected MUX channel ${logical_channel} (value ${mux_channel_value})."
    fi
    sleep 0.1 # Small delay for the MUX and sensor to stabilize

    # 2. Change the I2C address of the sensor on the selected channel
    log_message "INFO" "Attempting to change sensor address from ${DEFAULT_SENSOR_ADDRESS} to ${desired_address} using ${PYTHON_SCRIPT}."
    python_output=$(python3 "${PYTHON_SCRIPT}" --current "${DEFAULT_SENSOR_ADDRESS}" --desired "${desired_address}" 2>&1)
    python_exit_code=$?

    if [ ${python_exit_code} -ne 0 ]; then
        log_message "ERROR" "Python script failed to change address for sensor on channel ${logical_channel}."
        log_message "ERROR" "Python script output: ${python_output}"
        all_sensors_configured_successfully=false
        final_script_exit_code=1
        # Optionally, try to disable the current MUX channel again if things go wrong
        i2cset -y "${I2C_BUS}" "${MUX_ADDRESS}" 0x00 &> /dev/null
    else
        log_message "SUCCESS" "Python script successfully changed address for sensor on channel ${logical_channel} to ${desired_address}."
        log_message "INFO" "Python script output: ${python_output}" # Log script output even on success for details
    fi

    log_message "INFO" "Disabling MUX channel ${logical_channel} (writing 0x00 to MUX)."
    i2cset -y "${I2C_BUS}" "${MUX_ADDRESS}" 0x00 &> /dev/null
    sleep 0.1
done

log_message "INFO" "------------------------------------------------------------"

# 3. After setting all addresses, enable all desired channels on the MUX
# This should happen regardless of individual sensor success to ensure MUX is in a known state for i2cdetect
log_message "INFO" "Enabling all desired channels (0x0F) on MUX ${MUX_ADDRESS} for final scan."
i2cset_output=$(i2cset -y "${I2C_BUS}" "${MUX_ADDRESS}" 0x0F 2>&1)
if [ $? -ne 0 ]; then
    log_message "ERROR" "Failed to enable all MUX channels (0x0F). Output: ${i2cset_output}"
    # We still want to run i2cdetect, so don't exit yet, but mark overall failure
    all_sensors_configured_successfully=false # Mark this as overall not fully successful
    final_script_exit_code=1
else
    log_message "SUCCESS" "Successfully enabled all MUX channels (0x0F)."
fi

# 4. Run i2cdetect
log_message "INFO" "------------------------------------------------------------"
log_message "INFO" "Running i2cdetect on bus ${I2C_BUS} to verify final I2C device presence."
log_message "INFO" "Expected devices after successful configuration: ${MUX_ADDRESS} (MUX) and ${DESIRED_SENSOR_ADDRESSES[*]} (Sensors)."
echo "--- i2cdetect -y -r ${I2C_BUS} Output START ---" | tee -a "${LOG_FILE}"
i2cdetect_output=$(i2cdetect -y -r "${I2C_BUS}" 2>&1)
i2cdetect_exit_code=$?
echo "${i2cdetect_output}" | tee -a "${LOG_FILE}"
echo "--- i2cdetect -y -r ${I2C_BUS} Output END ---" | tee -a "${LOG_FILE}"

if [ ${i2cdetect_exit_code} -ne 0 ]; then
    log_message "ERROR" "i2cdetect command failed with exit code ${i2cdetect_exit_code}."
    # This usually means the bus itself has issues or i2cdetect had an internal problem.
    final_script_exit_code=1
else
    log_message "INFO" "i2cdetect completed. Please review its output above to confirm device addresses."
    # You could add more sophisticated parsing of i2cdetect output here if needed
    # to automatically verify if 0x20, 0x21, 0x22, 0x23, and 0x70 are present.
fi


# --- Final Summary ---
log_message "INFO" "------------------------------------------------------------"
if [ "$all_sensors_configured_successfully" = true ] && [ $final_script_exit_code -eq 0 ]; then
    log_message "SUCCESS" "Sensor I2C address configuration script completed successfully."
    log_message "INFO" "All sensors configured and MUX set to 0x0F."
else
    log_message "WARNING" "One or more steps in the sensor configuration failed or i2cdetect indicated issues."
    log_message "WARNING" "Please check the log file: ${LOG_FILE} for details."
    log_message "ERROR" "Script finished with errors."
    final_script_exit_code=1 # Ensure it's set if not already
fi

exit ${final_script_exit_code}
