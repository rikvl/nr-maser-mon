#!/usr/bin/env python3
#
# Requirement: pyserial
#

import logging
import os
import serial
import sys
import threading

from datetime import datetime

logfilename = "/var/log/maser.log"
metrics_dir = "/var/lib/node_exporter/textfile_collector/"
metrics_prefix = "maser"

# Create logger
logger = logging.getLogger(__name__)

logfile_format = logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S")
logfile_handler = logging.FileHandler(logfilename)
logfile_handler.setFormatter(logfile_format)
logger.addHandler(logfile_handler)

logstrm_format = logging.Formatter("%(message)s")
logstrm_handler = logging.StreamHandler()
logstrm_handler.setFormatter(logstrm_format)
logger.addHandler(logstrm_handler)

logger.setLevel(logging.DEBUG)

# Names of annalog channel sets and names of individual analog channels
analog_chan_sets = {
    "VOLTAGES": ["  p28  ", "  p18  ", "  p5   ", "  n18  ", "VACION ", "THRMREF", "  p00  ", " p2 REF"],
    "BUFFERS ": ["RCVR1  ", "TRANS  ", "SYNTH  ", "DIST   ", "  1    ", "  2    ", "  3    ", "  4    "],
    "MULT SEN": ["1p4 GHZ", "400KHZ ", "200MRC ", "20MHZ  ", "200MRF ", "200MLP ", "20 MMLT", "10 REF "],
    "CURRENTS": ["  p28  ", "BATCHG ", "VACPMP ", "SOURCE ", "STSEL  ", "H2PUR  "],
    "HEATERS ": [" RCVR  ", "MNCYL  ", "LOSUP  ", "OUTEL  ", "  CAV  ", "GAUGE  "],
    "CONTROL ": ["MNCRSE ", "UPNECK ", "LONECK ", "MNFINE ", "UPMAIN ", "LOMAIN "],
    " MISC   ": [" PK PH ", "  VCO  ", "   IF  ", "PRESS  ", " 1MHZ  ", " GAIN  ", "OFFSET ", "RAW REF"],
    " TEMP   ": ["SUP PLT", " RCVR  ", "  MAIN ", "TOPCAB ", "LOWCAB ", "OUTEL  ", " CAV LF", " CAV RT"],
}


def main(com_port_maser, com_port_nrcan):
    """Log metrics of NR Hydrogen Maser

    Parameters
    ----------
    com_port_maser : str
        Path to serial device connected to maser.
    com_port_nrcan : str
        Path to serial device connected to NRCan machine.
    """

    # Serial port settings: 2400/7-N-1
    baudrate = 2400
    bytesize = serial.SEVENBITS
    parity = serial.PARITY_NONE
    stopbits = serial.STOPBITS_ONE

    # Open serial port to NRCan
    ser_nrcan = serial.Serial(
        port=com_port_nrcan,
        baudrate=baudrate,
        parity=parity,
        stopbits=stopbits,
        bytesize=bytesize,
    )
    logger.info("Connected to NRCan on " + ser_nrcan.portstr)

    # Open serial port to maser
    ser_maser = serial.Serial(
        port=com_port_maser,
        baudrate=baudrate,
        parity=parity,
        stopbits=stopbits,
        bytesize=bytesize,
    )
    logger.info("Connected to Maser on " + ser_maser.portstr)

    # Create lock to serialize writes to log file
    lock = threading.Lock()

    # Create thread to relay messages from NRCan to maser
    nrcan_to_maser_thread = threading.Thread(
        target=relay_nrcan_to_maser,
        args=(ser_maser, ser_nrcan, lock)
    )
    nrcan_to_maser_thread.daemon = True
    nrcan_to_maser_thread.start()

    # Create thread to relay messages from maser to NRCan
    maser_to_nrcan_thread = threading.Thread(
        target=relay_maser_to_nrcan,
        args=(ser_maser, ser_nrcan, lock)
    )
    maser_to_nrcan_thread.daemon = True
    maser_to_nrcan_thread.start()

    # Main thread keeps going until keyboard interrupt
    try:
        while True:
            pass

    except KeyboardInterrupt:
        logger.info("Relay and logging stopped by keyboard interrupt")

        # Close serial port
        ser_maser.close()
        ser_nrcan.close()


def relay_nrcan_to_maser(ser_maser, ser_nrcan, lock):
    """Relay messages from NRCan to NR Hydrogen Maser and log them"""

    line = ""

    while True:
        # Read raw byte from serial port. Blocks until one byte is read.
        raw_byte = ser_nrcan.read()

        # Send raw byte to maser
        ser_maser.write(raw_byte)

        # Decode raw byte
        byte = raw_byte.decode()

        # Add byte to line
        line += byte

        # Detect end of input from F or D character
        if byte == "F" or byte == "D":
            with lock:
                # Write line to logs
                logger.info("NRCan: " + line)

            # Reset line variable
            line = ""


def relay_maser_to_nrcan(ser_maser, ser_nrcan, lock):
    """Relay messages from NR Hydrogen Maser to NRCan and log and process them"""

    line = ""

    while True:
        # Read raw byte from serial port. Blocks until one byte is read.
        raw_byte = ser_maser.read()

        # Send raw byte to NRCan
        ser_nrcan.write(raw_byte)

        # Decode raw byte
        byte = raw_byte.decode()

        # Add byte to line
        line += byte

        # Detect end of line from line feed character
        if byte == "\n":
            # Strip carriage return and line feed from line
            line = line.strip("\r\n")

            with lock:
                # Write line to logs
                logger.info("Maser: " + line)

            # Process line for metrics collection
            detect_metric_line(line)

            # Reset line variable
            line = ""


def detect_metric_line(line):
    """Detect relevant line with metrics and pass it to parser functions.

    Parameters
    ----------
    line : str
        Line of raw maser output.
    """

    if "SYN" in line:
        parse_status_line1(line)
    elif "DGSW" in line:
        parse_status_line2(line)
    else:
        analog_set_id = next((s for s in analog_chan_sets.keys() if s in line), False)
        if analog_set_id:
            parse_analog_chan_line(line, analog_set_id)


def parse_status_line1(line):
    """Parse raw maser status printout line 1.

    Parameters
    ----------
    line : str
        Line 1 of raw maser status printout.
    """

    data_string = ""

    # Name of this maser
    data_string += format_metric("info", labels={"name": line[0:8]})

    # UTC date and time as given by maser in format YR DOY HR MIN SEC
    try:
        maser_time_dt = datetime.strptime(line[9:24] + " +0000", "%y %j %H %M %S %z")
        maser_time_unix = maser_time_dt.timestamp()
    except ValueError:
        maser_time_unix = -1
    data_string += format_metric("utc_time", maser_time_unix)

    # Autotuner status
    data_string += format_metric("autotuner_status_raw", labels={"raw": line[25:45]})
    data_string += format_metric("autotuner_mode", labels={"mode": line[25]})
    data_string += format_metric("autotuner_h2flux_state", labels={"state": line[26]})
    data_string += format_metric("autotuner_measurement_state", labels={"state": line[27]})
    data_string += format_metric("autotuner_measurement_count_seconds", str2int(line[28:30]))
    data_string += format_metric("autotuner_h2flux_ctrl_device", labels={"device": line[30]})
    data_string += format_metric("autotuner_sign", labels={"sign": line[31]})
    data_string += format_metric("autotuner_max_diff", str2int(line[32:38]))
    data_string += format_metric("autotuner_shift_direction", labels={"direction": line[38]})
    data_string += format_metric("autotuner_bit_shift", str2int(line[39:41]))
    data_string += format_metric("autotuner_dac1_chan", str2int(line[41:43]))
    data_string += format_metric("autotuner_dac2_chan", str2int(line[43:45]))

    data_string += format_metric("autotuner_measurement_msb", str2int(line[46:48]))
    data_string += format_metric("autotuner_register_msb", str2int(line[49:51]))

    data_string += format_metric("autotuner_register_number", str2int(line[52:58]))

    # Synthesizer status
    data_string += format_metric("synthesizer_mode", labels={"mode": line[63]})
    data_string += format_metric("synthesizer_number_a", str2int(line[65:69]))
    data_string += format_metric("synthesizer_number_b", str2int(line[70:74]))
    data_string += format_metric("synthesizer_number_c", str2int(line[75:78]))

    # Write metrics to file
    write_metrics("status1", data_string)


def parse_status_line2(line):
    """Parse raw maser status printout line 2.

    Parameters
    ----------
    line : str
        Line 2 of raw maser status printout.
    """

    data_string = ""

    # Autotuner wait interval and count
    data_string += format_metric("autotuner_wait_interval_seconds", str2int(line[0:3]))
    data_string += format_metric("autotuner_count_seconds", str2int(line[5:9]))

    # Digital status word (convert from binary to decimal)
    data_string += format_metric("digital_status_word", str2int(line[15:27], 2))

    # Digital-to-analog converter control words
    data_string += format_metric("dac1_channel", str2int(line[35:37]))
    data_string += format_metric("dac1_msb", str2int(line[38:40]))
    data_string += format_metric("dac2_channel", str2int(line[41:43]))
    data_string += format_metric("dac2_msb", str2int(line[44:46]))

    # Write metrics to file
    write_metrics("status2", data_string)


def parse_analog_chan_line(line, analog_set_id):
    """Parse raw analog channels line.

    Parameters
    ----------
    line : str
        Line of raw analog channels metrics.
    analog_set_id : str
        Analog channel set identifier.
    """

    data_string = ""

    # Convert analog set id to label.
    analog_set_name = analog_set_id.strip().replace(" ", "_").lower()

    # Loop through all analog channels in set (eight, minus spares).
    for ichan, chan_id in enumerate(analog_chan_sets[analog_set_id]):
        # Convert analog channel id to label.
        chan_name = chan_id.strip().replace(" ", "_").lower()

        # Parse analog channel value from raw maser metric line.
        index_lower = 15 + ichan * 8
        index_upper = index_lower + 6
        chan_val = str2float(line[index_lower:index_upper])

        # Hack for I.F. sense metric, which overflows space.
        if chan_name == "if":
            chan_val = str2float(line[30:37])

        # Add metric to data string.
        metric_name = f"{analog_set_name}_{chan_name}"
        data_string += format_metric(metric_name, chan_val)

    # Write metrics to file.
    write_metrics(analog_set_name, data_string)


def str2int(s, base=10):
    """Convert string to integer with exception handling.

    Parameters
    ----------
    s : str
        String to parse.
    base : int
        Number format to convert to. Default value: 10
    """

    try:
        i = int(s, base)
    except ValueError:
        i = -1

    return i


def str2float(s):
    """Convert string to float with exception handling.

    Parameters
    ----------
    s : str
        String to parse.
    """

    try:
        f = float(s)
    except ValueError:
        f = -1

    return f


def format_metric(metric_name, value=1, labels={}):
    """Put metric in string formatted for Prometheus.

    Parameters
    ----------
    metric_name : str
        Name of metric.
    value : any
        Value of metric. Default value: 1
    labels : dict
        Dictionary of labels and their values. Optional.
    """

    # Prepare labels.
    labels_list = []
    for label_name, label_value in labels.items():
        labels_list.append(f'{label_name}="{label_value}"')
    labels_string = ", ".join(labels_list)
    if labels_string:
        labels_string = f"{{{labels_string}}}"

    # Format metric for Prometheus.
    metric_string = f"{metrics_prefix}_{metric_name}{labels_string} {value}\n"

    return metric_string


def write_metrics(file_id, data_string):
    """Write metrics to prom file for scraping by node_exporter textfile collector.

    First write metrics to temporary file, then rename temporary file to final file.
    This avoids node exporter seeing half a file.

    Parameters
    ----------
    file_id : str
        Base name of file.
    data_string : str
        String containing metrics.
    """

    final_path = f"{metrics_dir}{metrics_prefix}_{file_id}.prom"

    # Write out metrics to temporary file.
    temporary_path = f"{final_path}.$$"
    with open(temporary_path, "w") as fl:
        fl.write(data_string)

    # Rename temporary file to final file.
    os.rename(temporary_path, final_path)


if __name__ == "__main__":
    com_port_maser = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB1"
    com_port_nrcan = sys.argv[2] if len(sys.argv) > 2 else "/dev/ttyUSB0"
    sys.exit(main(com_port_maser=com_port_maser, com_port_nrcan=com_port_nrcan))