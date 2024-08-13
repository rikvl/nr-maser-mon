#!/usr/bin/env python3
#
# Requirement: pyserial
#

import os
import sys

import logging
import serial


logfilename = "/var/log/maser/nrcan-request.log"

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


def relay_maser_requests(com_port_maser, com_port_nrcan):
    """Relay requests from NRCan to NR Hydrogen Maser

    Parameters
    ----------
    com_port_maser : str
        Path to serial device connected to maser.
    com_port_nrcan : str
        Path to serial device connected to NRCan machine.
    """

    # Open serial port with settings 2400/7-N-1
    ser_maser = serial.Serial(
        port=com_port_maser,
        baudrate=2400,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.SEVENBITS,
    )
    logger.info("Connected to Maser: " + ser_maser.portstr)

    # Open serial port with settings 2400/7-N-1
    ser_nrcan = serial.Serial(
        port=com_port_nrcan,
        baudrate=2400,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.SEVENBITS,
    )
    logger.info("Connected to NRCan: " + ser_nrcan.portstr)

    line = ""

    # Keep going until keyboard interrupt
    try:
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
                # Write line to logs
                logger.info(line)

                # Reset line variable
                line = ""

    except KeyboardInterrupt:
        logger.info("Relay from NRCan to maser stopped")

    # Close serial port
    ser_maser.close()
    ser_nrcan.close()


if __name__ == "__main__":
    com_port_maser = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB1"
    com_port_nrcan = sys.argv[2] if len(sys.argv) > 2 else "/dev/ttyUSB0"
    sys.exit(relay_maser_requests(com_port_maser=com_port_maser, com_port_nrcan=com_port_nrcan))
