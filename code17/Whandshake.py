from multiprocessing import Process
from tuntap import TunTap
import socket
import time
import board
import busio
import digitalio
import adafruit_rfm9x
import numpy as np
import atexit
import ipaddress
import random
import threading

RADIO_FREQ_MHZT = 868.0  # Frequency of the radio in Mhz. Must match your
RADIO_FREQ_MHZR = 869.0

CS = digitalio.DigitalInOut(board.CE1)
RESET = digitalio.DigitalInOut(board.D25)

CS2 = digitalio.DigitalInOut(board.D17)
RESET2 = digitalio.DigitalInOut(board.D5)

spiR = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)
spiT = busio.SPI(board.D21, MOSI=board.D20, MISO=board.D19)

rfm9xR = adafruit_rfm9x.RFM9x(spiR, CS, RESET, RADIO_FREQ_MHZR)
rfm9xT = adafruit_rfm9x.RFM9x(spiT, CS2, RESET2, RADIO_FREQ_MHZT)

# Radio 1: Transmitter
# enable CRC checking
#rfm9xT.enable_crc = True
rfm9xT.node = 4
rfm9xT.destination = 3
rfm9xT.tx_power = 5
rfm9xT.spreading_factor = 10
rfm9xT.ack_retries = 1
#rfm9xT.signal_bandwidth = 125000
counterT = 0

# Radio 2: Receiver NOT WOKRING
# enable CRC checking
#rfm9xR.enable_crc = True
rfm9xR.node = 2
rfm9xR.destination = 1
rfm9xR.spreading_factor = 10
#rfm9xT.signal_bandwidth = 125000
counterR = 0

iface= 'tun2'
tun = TunTap(nic_type="Tun", nic_name="tun2")
#tun.config(ip="192.168.2.100", mask="255.255.255.0", gateway="192.168.0.1")
tun_ip = ""

ip_set = False
lock = threading.Lock()

def exit_handler():
    tun.close()

def transmit_message(message):
    print("SENDING: ", message.hex())
    rfm9xT.send(message)

def bits_to_bytes(bits: str):
    return bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))

def transmit():
    while True: # Checks that tun interface has an ip address
        buf = tun.read(252)
        #print("TUN BUFFER: ", buf)
        #tx_sock.sendto( buf, (RECEIVER_IP, UDP_PORT))
        rfm9xT.send(buf)

def receive():
    global lock

    while True:
        packet = rfm9xR.receive(with_header=True, timeout=5)
        lock.acquire()
        if packet is not None:
            # If ipv4 packet, write to tun interface:
            packet_hex = packet.hex()
            
            #print("hex: ", packet_hex)
            #print("PACKET: ", bytes(packet[4:]))
            if packet_hex[8:10] == "45": 
                tun.write(bytes(packet[4:]))
            elif packet_hex[:2] == "02":
                # if not  packet, decode:
                payload = ""
                for i in range(0, 9):
                    payload += str(format(int(packet_hex[i*2:(i*2)+2], 16), "08b")) # Translates each octet from bits to decimal
                
                print(payload[39], " - ", payload[40:])
                control_packet(payload[39], payload[40:])
        lock.release()

def control_packet(frame_type, data):
    global ip_set
    if frame_type == "0":
        print("\nData plane")
    elif frame_type == "1":
        print("\nControl plane")
        if ip_set == True:
            print("IP_SET")
            return

        print("my ip: ", data)
        tun_ip = ""
        for i in range(0, 4):
            tun_ip += str(int(data[i*8:(i*8)+8], 2)) # Translates each octet from bits to decimal
            if i != 3:
                tun_ip += "."
        print("IP: ", tun_ip)
        #tun.config(ip=tun_ip, mask="255.255.255.0", gateway="192.168.0.1")
        ip_set = True

def sensor_value_sender():
    # Get ip address
    ip = ipaddress.IPv4Address('192.168.2.5')
    control_frame = frame(1, ip)
    control_frame_bits = control_frame.createControlFrame()
    transmit_message(control_frame_bits)

    # Send random data to base station
    i = 0
    start_time = time.monotonic()
    while True:
        if time.monotonic() > start_time + 1: # Send different data
            if i % 3 == 0:
                temp = random.randint(-3, 10)
                data = "temperature,lund," + str(temp) + " degr C\n"
            elif i % 3 == 1:
                pressure = random.randint(990, 1050)
                data = "pressure,lund," + str(pressure) + "hPa\n"
            elif i % 3 == 2:
                level = random.randint(0, 4)
                data = "waterlevel,stockholm," + str(level) + "mm\n"
            data_frame = frame(0, data)
            data_frame_bits = data_frame.createDataFrame()
            transmit_message(data_frame_bits)
            i += 1
            start_time = time.monotonic()

class frame:
    frame_type = 0
    data = 0
    frame = 0
    length = 0

    def __init__(self, frame_type, data):
        self.frame_type = frame_type
        self.data = data

    def createControlFrame(self):
        frame = format(self.frame_type, "08b") # frane_type is on index 7 
        data_int = int(self.data)
        data_bit = format(data_int, "032b")
        frame += data_bit
        return bits_to_bytes(frame)
    
    def createDataFrame(self):
        frame = format(self.frame_type, "08b")
        data_bits = ''.join(format(ord(i), '08b') for i in self.data)
        for i in range(512 - len(data_bits)):
            data_bits += "0"

        frame += data_bits
        return bits_to_bytes(frame)

           
if __name__ == "__main__":
    atexit.register(exit_handler)
    tx_process = Process(target=transmit)
    rx_process = Process(target=receive)
    svs_process = Process(target=sensor_value_sender)

    rx_process.start()
    time.sleep(1)
    tx_process.start()
    time.sleep(1)
    svs_process.start()

    tx_process.join()
    rx_process.join()
    tun.close()