using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

// Reading and writing serial EEPROMs with an FTDI FT232H (MPSSE engine used as fast GPIO).
//
//   93Cxx  (Microwire)  : D0 = CLK(SK)   D1 = DI    D2 = DO    D3 = CS (active high)
//   24Cxx  (I2C)        : D0 = SCL       D1 = SDA   (4.7k pull-ups to the chip VCC)
//   95xxx  (SPI, mode 0): D0 = SCK       D1 = MOSI  D2 = MISO  D3 = CS (active low)
//
// Everything is driven with the two MPSSE commands "set data bits low byte" (0x80) and
// "read data bits low byte" (0x81), so the chip logic can be tested against simulated chips
// (see IFtdiPort) without any hardware.
namespace DashForgeProgrammer
{
	internal interface IFtdiPort : IDisposable
	{
		void Write(byte[] data, int count);

		byte[] Read(int count);
	}

	internal sealed class FtdiDeviceInfo
	{
		public int Index;

		public string Serial;

		public string Description;

		public override string ToString()
		{
			return "FT232H" + ((Serial.Length > 0) ? " · " + Serial : "");
		}
	}

	internal sealed class ProgrammerException : Exception
	{
		public ProgrammerException(string message)
			: base(message)
		{
		}
	}

	// Real FTDI D2XX access (ftd2xx.dll is installed with the FTDI driver).
	internal sealed class D2xxPort : IFtdiPort
	{
		private const string Dll = "ftd2xx.dll";

		private IntPtr handle;

		[DllImport(Dll)]
		private static extern int FT_CreateDeviceInfoList(out uint count);

		[DllImport(Dll, CharSet = CharSet.Ansi)]
		private static extern int FT_GetDeviceInfoDetail(uint index, out uint flags, out uint type, out uint id, out uint locId, StringBuilder serial, StringBuilder description, out IntPtr handle);

		[DllImport(Dll)]
		private static extern int FT_Open(int index, out IntPtr handle);

		[DllImport(Dll)]
		private static extern int FT_Close(IntPtr handle);

		[DllImport(Dll)]
		private static extern int FT_ResetDevice(IntPtr handle);

		[DllImport(Dll)]
		private static extern int FT_SetUSBParameters(IntPtr handle, uint inSize, uint outSize);

		[DllImport(Dll)]
		private static extern int FT_SetChars(IntPtr handle, byte eventChar, byte eventEnable, byte errorChar, byte errorEnable);

		[DllImport(Dll)]
		private static extern int FT_SetTimeouts(IntPtr handle, uint readTimeout, uint writeTimeout);

		[DllImport(Dll)]
		private static extern int FT_SetLatencyTimer(IntPtr handle, byte latency);

		[DllImport(Dll)]
		private static extern int FT_SetFlowControl(IntPtr handle, ushort flowControl, byte xon, byte xoff);

		[DllImport(Dll)]
		private static extern int FT_SetBitMode(IntPtr handle, byte mask, byte mode);

		[DllImport(Dll)]
		private static extern int FT_Purge(IntPtr handle, uint mask);

		[DllImport(Dll)]
		private static extern int FT_Write(IntPtr handle, byte[] buffer, uint bytes, out uint written);

		[DllImport(Dll)]
		private static extern int FT_Read(IntPtr handle, byte[] buffer, uint bytes, out uint read);

		[DllImport(Dll)]
		private static extern int FT_GetQueueStatus(IntPtr handle, out uint rxBytes);

		private const uint FT_DEVICE_232H = 8u;

		public static List<FtdiDeviceInfo> Enumerate()
		{
			List<FtdiDeviceInfo> list = new List<FtdiDeviceInfo>();
			uint count;
			try
			{
				if (FT_CreateDeviceInfoList(out count) != 0)
				{
					return list;
				}
			}
			catch (DllNotFoundException)
			{
				throw new ProgrammerException("The FTDI driver (ftd2xx.dll) is not installed. Install the FTDI D2XX driver from ftdichip.com and plug in the FT232H.");
			}
			catch (BadImageFormatException)
			{
				throw new ProgrammerException("The FTDI driver (ftd2xx.dll) does not match this program (64-bit). Reinstall the FTDI D2XX driver.");
			}
			for (uint i = 0u; i < count; i++)
			{
				StringBuilder serial = new StringBuilder(64);
				StringBuilder description = new StringBuilder(128);
				uint flags;
				uint type;
				uint id;
				uint locId;
				IntPtr h;
				if (FT_GetDeviceInfoDetail(i, out flags, out type, out id, out locId, serial, description, out h) == 0 && type == FT_DEVICE_232H)
				{
					list.Add(new FtdiDeviceInfo
					{
						Index = (int)i,
						Serial = serial.ToString(),
						Description = description.ToString()
					});
				}
			}
			return list;
		}

		public D2xxPort(int index)
		{
			if (FT_Open(index, out handle) != 0)
			{
				throw new ProgrammerException("Could not open the FT232H. Close any other program that uses it and try again.");
			}
			try
			{
				Check(FT_ResetDevice(handle), "reset");
				FT_Purge(handle, 3u);
				Check(FT_SetUSBParameters(handle, 65536u, 65535u), "USB parameters");
				Check(FT_SetChars(handle, 0, 0, 0, 0), "characters");
				Check(FT_SetTimeouts(handle, 5000u, 5000u), "timeouts");
				Check(FT_SetLatencyTimer(handle, 1), "latency");
				Check(FT_SetFlowControl(handle, 256, 0, 0), "flow control");
				Check(FT_SetBitMode(handle, 0, 0), "bit mode reset");
				Check(FT_SetBitMode(handle, 0, 2), "MPSSE mode");
				Thread.Sleep(50);
				FT_Purge(handle, 3u);
			}
			catch (Exception)
			{
				Dispose();
				throw;
			}
		}

		private static void Check(int status, string what)
		{
			if (status != 0)
			{
				throw new ProgrammerException("FT232H setup failed (" + what + ", code " + status + ").");
			}
		}

		public void Write(byte[] data, int count)
		{
			byte[] buffer = data;
			if (data.Length != count)
			{
				buffer = new byte[count];
				Array.Copy(data, buffer, count);
			}
			uint written;
			if (FT_Write(handle, buffer, (uint)count, out written) != 0 || written != (uint)count)
			{
				throw new ProgrammerException("USB write to the FT232H failed. Check the cable.");
			}
		}

		public byte[] Read(int count)
		{
			byte[] result = new byte[count];
			int have = 0;
			DateTime deadline = DateTime.UtcNow.AddSeconds(5.0);
			while (have < count)
			{
				uint queued;
				if (FT_GetQueueStatus(handle, out queued) != 0)
				{
					throw new ProgrammerException("USB read from the FT232H failed.");
				}
				if (queued == 0)
				{
					if (DateTime.UtcNow > deadline)
					{
						throw new ProgrammerException("The FT232H did not answer (timeout).");
					}
					Thread.Sleep(1);
					continue;
				}
				byte[] chunk = new byte[Math.Min((int)queued, count - have)];
				uint read;
				if (FT_Read(handle, chunk, (uint)chunk.Length, out read) != 0)
				{
					throw new ProgrammerException("USB read from the FT232H failed.");
				}
				Array.Copy(chunk, 0, result, have, (int)read);
				have += (int)read;
			}
			return result;
		}

		public void Dispose()
		{
			if (handle != IntPtr.Zero)
			{
				try
				{
					FT_SetBitMode(handle, 0, 0);
				}
				catch (Exception)
				{
				}
				FT_Close(handle);
				handle = IntPtr.Zero;
			}
		}
	}

	// Batches "set / read pins" MPSSE commands.
	internal sealed class Gpio
	{
		private readonly IFtdiPort port;

		private readonly List<byte> buffer = new List<byte>(1 << 16);

		private readonly List<byte> results = new List<byte>();

		private int pending;

		private readonly int repeat;

		public Gpio(IFtdiPort port, int repeat)
		{
			this.port = port;
			this.repeat = Math.Max(1, repeat);
		}

		// Sync with the MPSSE engine and configure it (60 MHz clock, no divide-by-5, no adaptive/3-phase clocking).
		public void Init()
		{
			port.Write(new byte[1] { 133 }, 1);
			port.Write(new byte[1] { 171 }, 1);
			byte[] answer = port.Read(2);
			if (answer[0] != 250 || answer[1] != 171)
			{
				throw new ProgrammerException("The FT232H is not answering in MPSSE mode.");
			}
			byte[] setup = new byte[7] { 138, 151, 141, 134, 4, 0, 133 };
			port.Write(setup, setup.Length);
		}

		public void Set(byte value, byte direction)
		{
			for (int i = 0; i < repeat; i++)
			{
				buffer.Add(128);
				buffer.Add(value);
				buffer.Add(direction);
			}
			if (buffer.Count > 40000 && pending == 0)
			{
				WriteOut();
			}
		}

		public void Read()
		{
			buffer.Add(129);
			pending++;
			if (pending >= 400)
			{
				FlushInternal();
			}
		}

		public byte[] Take()
		{
			FlushInternal();
			byte[] array = results.ToArray();
			results.Clear();
			return array;
		}

		private void WriteOut()
		{
			if (buffer.Count > 0)
			{
				byte[] data = buffer.ToArray();
				buffer.Clear();
				port.Write(data, data.Length);
			}
		}

		private void FlushInternal()
		{
			if (pending > 0)
			{
				buffer.Add(135);
			}
			WriteOut();
			if (pending > 0)
			{
				results.AddRange(port.Read(pending));
				pending = 0;
			}
		}
	}

	internal sealed class ChipInfo
	{
		public string Name;

		public string Family;

		public int Size;

		public int Page;

		public int Mw8;

		public int Mw16;

		public override string ToString()
		{
			return Name;
		}
	}

	internal static class Chips
	{
		public static readonly ChipInfo[] All = new ChipInfo[15]
		{
			new ChipInfo { Name = "93C46", Family = "Microwire", Size = 128, Mw8 = 7, Mw16 = 6 },
			new ChipInfo { Name = "93C56", Family = "Microwire", Size = 256, Mw8 = 9, Mw16 = 8 },
			new ChipInfo { Name = "93C66", Family = "Microwire", Size = 512, Mw8 = 9, Mw16 = 8 },
			new ChipInfo { Name = "93C76", Family = "Microwire", Size = 1024, Mw8 = 11, Mw16 = 10 },
			new ChipInfo { Name = "93C86", Family = "Microwire", Size = 2048, Mw8 = 11, Mw16 = 10 },
			new ChipInfo { Name = "24C32", Family = "I2C", Size = 4096, Page = 32 },
			new ChipInfo { Name = "24C64", Family = "I2C", Size = 8192, Page = 32 },
			new ChipInfo { Name = "24C128", Family = "I2C", Size = 16384, Page = 64 },
			new ChipInfo { Name = "24C256", Family = "I2C", Size = 32768, Page = 64 },
			new ChipInfo { Name = "24C512", Family = "I2C", Size = 65536, Page = 128 },
			new ChipInfo { Name = "95128", Family = "SPI", Size = 16384, Page = 64 },
			new ChipInfo { Name = "95256", Family = "SPI", Size = 32768, Page = 64 },
			new ChipInfo { Name = "24C16", Family = "I2C1", Size = 2048, Page = 16 },
			new ChipInfo { Name = "24C08", Family = "I2C1", Size = 1024, Page = 16 },
			new ChipInfo { Name = "24C04", Family = "I2C1", Size = 512, Page = 16 }
		};

		public static ChipInfo Find(string name)
		{
			foreach (ChipInfo chip in All)
			{
				if (string.Equals(chip.Name, name, StringComparison.OrdinalIgnoreCase))
				{
					return chip;
				}
			}
			return null;
		}
	}

	internal sealed class ProgramOptions
	{
		public bool X16 = true;

		public bool SwapBytes;

		public int DeviceAddress;

		public int Repeat = 6;
	}

	internal sealed class EepromProgrammer
	{
		private readonly IFtdiPort port;

		private readonly Gpio gpio;

		private readonly ChipInfo chip;

		private readonly ProgramOptions options;

		private readonly Action<string, int> progress;

		private readonly Func<bool> cancelled;

		public EepromProgrammer(IFtdiPort port, ChipInfo chip, ProgramOptions options, Action<string, int> progress, Func<bool> cancelled)
		{
			this.port = port;
			this.chip = chip;
			this.options = options;
			this.progress = progress ?? ((Action<string, int>)delegate
			{
			});
			this.cancelled = cancelled ?? ((Func<bool>)(() => false));
			gpio = new Gpio(port, options.Repeat);
			gpio.Init();
		}

		private void Tick(string text, long done, long total)
		{
			if (cancelled())
			{
				throw new ProgrammerException("Cancelled.");
			}
			progress(text, (int)((total == 0) ? 100 : (done * 100 / total)));
		}

		private void Release()
		{
			gpio.Set(0, 0);
			gpio.Take();
		}

		public byte[] Read()
		{
			try
			{
				switch (chip.Family)
				{
				case "Microwire":
					return MwRead();
				case "SPI":
					return SpiRead();
				default:
					return I2cRead();
				}
			}
			finally
			{
				Release();
			}
		}

		public void Write(byte[] data, byte[] current)
		{
			if (data.Length != chip.Size)
			{
				throw new ProgrammerException("The data is " + data.Length + " bytes but " + chip.Name + " holds " + chip.Size + " bytes.");
			}
			if (current != null && current.Length != data.Length)
			{
				current = null;
			}
			try
			{
				switch (chip.Family)
				{
				case "Microwire":
					MwWrite(data, current);
					break;
				case "SPI":
					SpiWrite(data, current);
					break;
				default:
					I2cWrite(data, current);
					break;
				}
			}
			finally
			{
				Release();
			}
		}

		public static int FirstDifference(byte[] a, byte[] b)
		{
			if (a.Length != b.Length)
			{
				return 0;
			}
			for (int i = 0; i < a.Length; i++)
			{
				if (a[i] != b[i])
				{
					return i;
				}
			}
			return -1;
		}

		// ------------------------------------------------------------------ Microwire (93Cxx)
		private const byte MwDirection = 11;

		private void MwSet(bool clk, bool di, bool cs)
		{
			gpio.Set((byte)((clk ? 1 : 0) | (di ? 2 : 0) | (cs ? 8 : 0)), MwDirection);
		}

		private void MwBit(bool bit)
		{
			MwSet(clk: false, bit, cs: true);
			MwSet(clk: true, bit, cs: true);
		}

		private int MwAddrBits()
		{
			return options.X16 ? chip.Mw16 : chip.Mw8;
		}

		private void MwCommand(int opcode, int address)
		{
			int bits = MwAddrBits();
			MwSet(clk: false, di: false, cs: false);
			MwBit(bit: true);
			MwBit((opcode & 2) != 0);
			MwBit((opcode & 1) != 0);
			for (int i = bits - 1; i >= 0; i--)
			{
				MwBit(((address >> i) & 1) != 0);
			}
		}

		private void MwEnd()
		{
			MwSet(clk: false, di: false, cs: true);
			MwSet(clk: false, di: false, cs: false);
		}

		private int MwUnits()
		{
			return options.X16 ? (chip.Size / 2) : chip.Size;
		}

		private void MwEnableWrites(bool enable)
		{
			int bits = MwAddrBits();
			MwCommand(0, enable ? (3 << (bits - 2)) : 0);
			MwEnd();
			gpio.Take();
		}

		private byte[] MwRead()
		{
			int unitBits = options.X16 ? 16 : 8;
			int units = MwUnits();
			int totalBits = units * unitBits;
			byte[] data = new byte[chip.Size];
			MwCommand(2, 0);
			int bitIndex = 0;
			int byteIndex = 0;
			int current = 0;
			int wordBitCount = 0;
			List<byte> raw = new List<byte>(chip.Size);
			for (int i = 0; i < totalBits; i++)
			{
				MwSet(clk: false, di: false, cs: true);
				MwSet(clk: true, di: false, cs: true);
				gpio.Read();
				bitIndex++;
				if (bitIndex % 2048 == 0)
				{
					byte[] chunk = gpio.Take();
					foreach (byte b in chunk)
					{
						Accumulate(b, data, ref byteIndex, ref current, ref wordBitCount, unitBits);
					}
					Tick("Reading " + chip.Name, bitIndex, totalBits);
				}
			}
			MwEnd();
			byte[] rest = gpio.Take();
			foreach (byte b2 in rest)
			{
				Accumulate(b2, data, ref byteIndex, ref current, ref wordBitCount, unitBits);
			}
			Tick("Reading " + chip.Name, totalBits, totalBits);
			return data;
		}

		private void Accumulate(byte pins, byte[] data, ref int byteIndex, ref int word, ref int bitCount, int unitBits)
		{
			word = (word << 1) | (((pins & 4) != 0) ? 1 : 0);
			bitCount++;
			if (bitCount != unitBits)
			{
				return;
			}
			if (unitBits == 16)
			{
				int high = (word >> 8) & 0xFF;
				int low = word & 0xFF;
				data[byteIndex++] = (byte)(options.SwapBytes ? low : high);
				data[byteIndex++] = (byte)(options.SwapBytes ? high : low);
			}
			else
			{
				data[byteIndex++] = (byte)word;
			}
			word = 0;
			bitCount = 0;
		}

		private int MwUnitValue(byte[] data, int unit)
		{
			if (options.X16)
			{
				int a = data[unit * 2];
				int b = data[unit * 2 + 1];
				return options.SwapBytes ? ((b << 8) | a) : ((a << 8) | b);
			}
			return data[unit];
		}

		private void MwWrite(byte[] data, byte[] current)
		{
			int unitBits = options.X16 ? 16 : 8;
			int units = MwUnits();
			int written = 0;
			MwEnableWrites(enable: true);
			for (int unit = 0; unit < units; unit++)
			{
				int value = MwUnitValue(data, unit);
				if (current != null && MwUnitValue(current, unit) == value)
				{
					continue;
				}
				MwCommand(1, unit);
				for (int i = unitBits - 1; i >= 0; i--)
				{
					MwBit(((value >> i) & 1) != 0);
				}
				MwSet(clk: false, di: false, cs: true);
				MwSet(clk: false, di: false, cs: false);
				MwSet(clk: false, di: false, cs: true);
				bool ready = false;
				for (int tries = 0; tries < 60; tries++)
				{
					gpio.Read();
					byte[] state = gpio.Take();
					if ((state[0] & 4) != 0)
					{
						ready = true;
						break;
					}
					Thread.Sleep(1);
				}
				MwSet(clk: false, di: false, cs: false);
				gpio.Take();
				if (!ready)
				{
					throw new ProgrammerException("The chip did not finish writing word " + unit + ". Check wiring, power and the ORG pin.");
				}
				written++;
				if (written % 16 == 0)
				{
					Tick("Writing " + chip.Name, unit, units);
				}
			}
			MwEnableWrites(enable: false);
			Tick("Writing " + chip.Name, units, units);
		}

		// ------------------------------------------------------------------ I2C (24Cxx)
		private void I2cLines(bool scl, bool sda)
		{
			gpio.Set(0, (byte)((scl ? 0 : 1) | (sda ? 0 : 2)));
		}

		private void I2cStart()
		{
			I2cLines(scl: true, sda: true);
			I2cLines(scl: true, sda: false);
			I2cLines(scl: false, sda: false);
		}

		private void I2cStop()
		{
			I2cLines(scl: false, sda: false);
			I2cLines(scl: true, sda: false);
			I2cLines(scl: true, sda: true);
		}

		private void I2cWriteBit(bool bit)
		{
			I2cLines(scl: false, bit);
			I2cLines(scl: true, bit);
			I2cLines(scl: false, bit);
		}

		private void I2cReadBit()
		{
			I2cLines(scl: false, sda: true);
			I2cLines(scl: true, sda: true);
			gpio.Read();
			I2cLines(scl: false, sda: true);
		}

		// Writes a byte and queues one read for the acknowledge bit.
		private void I2cWriteByte(int value)
		{
			for (int i = 7; i >= 0; i--)
			{
				I2cWriteBit(((value >> i) & 1) != 0);
			}
			I2cReadBit();
		}

		private static bool Acked(byte pins)
		{
			return (pins & 2) == 0;
		}

		private int I2cControl(int offset, bool read)
		{
			int device = 160 | ((options.DeviceAddress & 7) << 1);
			if (chip.Family == "I2C1")
			{
				device |= (offset >> 8) << 1;
			}
			return device | (read ? 1 : 0);
		}

		private void I2cAddress(int offset)
		{
			if (chip.Family == "I2C1")
			{
				I2cWriteByte(offset & 0xFF);
			}
			else
			{
				I2cWriteByte((offset >> 8) & 0xFF);
				I2cWriteByte(offset & 0xFF);
			}
		}

		private int I2cAddressBytes()
		{
			return (chip.Family == "I2C1") ? 1 : 2;
		}

		private byte[] I2cRead()
		{
			byte[] data = new byte[chip.Size];
			int block = 256;
			for (int offset = 0; offset < chip.Size; offset += block)
			{
				int length = Math.Min(block, chip.Size - offset);
				I2cStart();
				I2cWriteByte(I2cControl(offset, read: false));
				I2cAddress(offset);
				I2cLines(scl: false, sda: true);
				I2cLines(scl: true, sda: true);
				I2cLines(scl: true, sda: false);
				I2cLines(scl: false, sda: false);
				I2cWriteByte(I2cControl(offset, read: true));
				for (int i = 0; i < length; i++)
				{
					for (int bit = 0; bit < 8; bit++)
					{
						I2cReadBit();
					}
					I2cWriteBit(i == length - 1);
				}
				I2cStop();
				byte[] pins = gpio.Take();
				int headerAcks = 2 + I2cAddressBytes();
				for (int h = 0; h < headerAcks; h++)
				{
					if (!Acked(pins[h]))
					{
						throw new ProgrammerException("No response from the EEPROM. Check wiring, power, the SDA/SCL pull-up resistors and the A0-A2 pins.");
					}
				}
				for (int j = 0; j < length; j++)
				{
					int value = 0;
					for (int k = 0; k < 8; k++)
					{
						value = (value << 1) | (((pins[headerAcks + j * 8 + k] & 2) != 0) ? 1 : 0);
					}
					data[offset + j] = (byte)value;
				}
				Tick("Reading " + chip.Name, offset + length, chip.Size);
			}
			return data;
		}

		private void I2cWrite(byte[] data, byte[] current)
		{
			int page = chip.Page;
			for (int offset = 0; offset < chip.Size; offset += page)
			{
				bool same = current != null;
				if (same)
				{
					for (int i = 0; i < page; i++)
					{
						if (data[offset + i] != current[offset + i])
						{
							same = false;
							break;
						}
					}
				}
				if (!same)
				{
					I2cStart();
					I2cWriteByte(I2cControl(offset, read: false));
					I2cAddress(offset);
					for (int j = 0; j < page; j++)
					{
						I2cWriteByte(data[offset + j]);
					}
					I2cStop();
					byte[] pins = gpio.Take();
					int expected = 1 + I2cAddressBytes() + page;
					for (int k = 0; k < expected; k++)
					{
						if (!Acked(pins[k]))
						{
							throw new ProgrammerException("The EEPROM stopped answering while writing at 0x" + offset.ToString("X") + ". Check wiring, power and the write-protect (WP) pin.");
						}
					}
					bool ready = false;
					for (int tries = 0; tries < 100; tries++)
					{
						I2cStart();
						I2cWriteByte(I2cControl(offset, read: false));
						I2cStop();
						byte[] poll = gpio.Take();
						if (Acked(poll[0]))
						{
							ready = true;
							break;
						}
						Thread.Sleep(1);
					}
					if (!ready)
					{
						throw new ProgrammerException("The EEPROM did not finish the write cycle at 0x" + offset.ToString("X") + ".");
					}
				}
				Tick("Writing " + chip.Name, offset + page, chip.Size);
			}
		}

		// ------------------------------------------------------------------ SPI (95xxx), mode 0
		private const byte SpiDirection = 11;

		private void SpiSet(bool sck, bool mosi, bool cs)
		{
			gpio.Set((byte)((sck ? 1 : 0) | (mosi ? 2 : 0) | (cs ? 8 : 0)), SpiDirection);
		}

		private void SpiSelect()
		{
			SpiSet(sck: false, mosi: false, cs: true);
			SpiSet(sck: false, mosi: false, cs: false);
		}

		private void SpiDeselect()
		{
			SpiSet(sck: false, mosi: false, cs: false);
			SpiSet(sck: false, mosi: false, cs: true);
		}

		private void SpiSend(int value)
		{
			for (int i = 7; i >= 0; i--)
			{
				bool bit = ((value >> i) & 1) != 0;
				SpiSet(sck: false, bit, cs: false);
				SpiSet(sck: true, bit, cs: false);
			}
			SpiSet(sck: false, mosi: false, cs: false);
		}

		private void SpiReceiveByte()
		{
			for (int i = 0; i < 8; i++)
			{
				SpiSet(sck: false, mosi: false, cs: false);
				SpiSet(sck: true, mosi: false, cs: false);
				gpio.Read();
			}
			SpiSet(sck: false, mosi: false, cs: false);
		}

		private static int SpiByte(byte[] pins, int index)
		{
			int value = 0;
			for (int i = 0; i < 8; i++)
			{
				value = (value << 1) | (((pins[index + i] & 4) != 0) ? 1 : 0);
			}
			return value;
		}

		private int SpiStatus()
		{
			SpiSelect();
			SpiSend(5);
			SpiReceiveByte();
			SpiDeselect();
			byte[] pins = gpio.Take();
			return SpiByte(pins, 0);
		}

		private byte[] SpiRead()
		{
			byte[] data = new byte[chip.Size];
			int block = 512;
			for (int offset = 0; offset < chip.Size; offset += block)
			{
				int length = Math.Min(block, chip.Size - offset);
				SpiSelect();
				SpiSend(3);
				SpiSend((offset >> 8) & 0xFF);
				SpiSend(offset & 0xFF);
				for (int i = 0; i < length; i++)
				{
					SpiReceiveByte();
				}
				SpiDeselect();
				byte[] pins = gpio.Take();
				for (int j = 0; j < length; j++)
				{
					data[offset + j] = (byte)SpiByte(pins, j * 8);
				}
				Tick("Reading " + chip.Name, offset + length, chip.Size);
			}
			return data;
		}

		private void SpiWrite(byte[] data, byte[] current)
		{
			int status = SpiStatus();
			if ((status & 0x0C) != 0)
			{
				throw new ProgrammerException("The chip is block-protected (status register = 0x" + status.ToString("X2") + "). Remove the protection first.");
			}
			int page = chip.Page;
			for (int offset = 0; offset < chip.Size; offset += page)
			{
				bool same = current != null;
				if (same)
				{
					for (int i = 0; i < page; i++)
					{
						if (data[offset + i] != current[offset + i])
						{
							same = false;
							break;
						}
					}
				}
				if (!same)
				{
					SpiSelect();
					SpiSend(6);
					SpiDeselect();
					SpiSelect();
					SpiSend(2);
					SpiSend((offset >> 8) & 0xFF);
					SpiSend(offset & 0xFF);
					for (int j = 0; j < page; j++)
					{
						SpiSend(data[offset + j]);
					}
					SpiDeselect();
					gpio.Take();
					bool ready = false;
					for (int tries = 0; tries < 100; tries++)
					{
						if ((SpiStatus() & 1) == 0)
						{
							ready = true;
							break;
						}
						Thread.Sleep(1);
					}
					if (!ready)
					{
						throw new ProgrammerException("The chip did not finish the write cycle at 0x" + offset.ToString("X") + ".");
					}
				}
				Tick("Writing " + chip.Name, offset + page, chip.Size);
			}
		}
	}
}
