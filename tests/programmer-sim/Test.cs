using System;
using System.Collections.Generic;
using DashForgeProgrammer;

// Bit-level simulation of an FT232H + EEPROM chips to test the programmer logic without hardware.
abstract class ChipSim
{
	public abstract byte Update(byte master);   // pins as seen after master drive (released = 1); returns final pins
	public virtual byte Sample(byte last) { return last; }
	public int WriteOps;
}

class FakeFtdi : IFtdiPort
{
	byte val, dir;
	byte last = 0xFF;
	readonly Queue<byte> rx = new Queue<byte>();
	readonly ChipSim chip;
	public FakeFtdi(ChipSim chip) { this.chip = chip; last = Master(); if (chip != null) last = chip.Update(last); }
	byte Master() { byte m = 0; for (int i = 0; i < 8; i++) { bool drive = ((dir >> i) & 1) != 0; int level = drive ? ((val >> i) & 1) : 1; m |= (byte)(level << i); } return m; }
	public void Write(byte[] data, int count)
	{
		int i = 0;
		while (i < count)
		{
			byte c = data[i++];
			switch (c)
			{
				case 0x85: case 0x8A: case 0x97: case 0x8D: case 0x8C: case 0x87: break;
				case 0x86: i += 2; break;
				case 0xAB: rx.Enqueue(0xFA); rx.Enqueue(0xAB); break;
				case 0x80:
					val = data[i++]; dir = data[i++];
					last = Master(); if (chip != null) last = chip.Update(last);
					break;
				case 0x81:
					byte s = chip != null ? chip.Sample(last) : last;
					rx.Enqueue(s); break;
				default: throw new Exception("unexpected MPSSE command 0x" + c.ToString("X2"));
			}
		}
	}
	public byte[] Read(int count)
	{
		if (rx.Count < count) throw new ProgrammerException("sim: not enough data (" + rx.Count + " < " + count + ")");
		byte[] r = new byte[count]; for (int i = 0; i < count; i++) r[i] = rx.Dequeue(); return r;
	}
	public void Dispose() { }
}

// ---------------------------------------------------------------- I2C 24Cxx
class I2cSim : ChipSim
{
	public byte[] Mem; int page; int addrBytes; int busy;
	int prevScl = 1, prevSda = 1;
	bool slaveLow;
	int state; // 0 idle, 1 rx, 2 ack, 3 tx, 4 waitack
	int shift, bits, phase, ptr, wr;
	bool rw; byte ackNextState;
	List<(int, byte)> pend = new List<(int, byte)>();
	int txByte, txBit; bool masterAck;
	int hi;
	public I2cSim(int size, int page, int addrBytes) { Mem = new byte[size]; for (int i = 0; i < size; i++) Mem[i] = 0xFF; this.page = page; this.addrBytes = addrBytes; }
	public override byte Update(byte m)
	{
		int scl = m & 1; int sdaM = (m >> 1) & 1; int sda = slaveLow ? 0 : sdaM;
		if (scl == 1 && prevScl == 1)
		{
			if (prevSda == 1 && sda == 0 && !slaveLow) { state = 1; bits = 0; shift = 0; phase = 0; slaveLow = false; pend.Clear(); wr = 0; }
			else if (prevSda == 0 && sda == 1 && sdaM == 1) { Stop(); }
		}
		if (prevScl == 0 && scl == 1) Rising(sda);
		if (prevScl == 1 && scl == 0) Falling();
		prevScl = scl; prevSda = slaveLow ? 0 : sdaM;
		byte outp = m;
		if (slaveLow) outp = (byte)(outp & ~2);
		return outp;
	}
	void Stop()
	{
		if (state == 0) return;
		if (pend.Count > 0) { foreach (var (a, b) in pend) Mem[a % Mem.Length] = b; pend.Clear(); busy = 3; WriteOps++; }
		state = 0; slaveLow = false;
	}
	void Rising(int sda)
	{
		if (state == 1) { shift = ((shift << 1) | sda) & 0xFF; bits++; }
		else if (state == 4) { masterAck = sda == 0; }
	}
	void Falling()
	{
		if (state == 1 && bits == 8)
		{
			bool ack = false;
			if (phase == 0)
			{
				bool match = (shift & 0xF0) == 0xA0;
				rw = (shift & 1) != 0; hi = (addrBytes == 1) ? ((shift >> 1) & 7) : 0;
				if (match && busy > 0) { busy--; ack = false; }
				else ack = match;
				if (ack) { if (rw) { ackNextState = 3; } else { ackNextState = 1; } phase = rw ? 9 : 1; }
				else ackNextState = 0;
			}
			else if (phase >= 1 && phase <= addrBytes)
			{
				if (phase == 1) ptr = 0;
				ptr = (ptr << 8) | shift; if (addrBytes == 1) ptr = (hi << 8) | shift; ack = true; phase++; if (phase == addrBytes + 1) { phase = 10; wr = ptr; }
				ackNextState = 1;
			}
			else if (phase == 10)
			{
				pend.Add((wr, (byte)shift));
				int pageStart = wr - (wr % page); wr = pageStart + ((wr + 1 - pageStart) % page); ack = true; ackNextState = 1;
			}
			else { ackNextState = 0; }
			slaveLow = ack; state = 2; bits = 0; return;
		}
		if (state == 2)
		{
			slaveLow = false;
			state = ackNextState;
			if (state == 1) { bits = 0; shift = 0; }
			if (state == 3) { if (addrBytes == 1) ptr = (hi << 8) | (ptr & 0xFF); txByte = Mem[ptr % Mem.Length]; txBit = 0; slaveLow = ((txByte >> 7) & 1) == 0; }
			return;
		}
		if (state == 3)
		{
			txBit++;
			if (txBit == 8) { slaveLow = false; state = 4; return; }
			slaveLow = ((txByte >> (7 - txBit)) & 1) == 0; return;
		}
		if (state == 4)
		{
			if (masterAck) { ptr = (ptr + 1) % Mem.Length; txByte = Mem[ptr]; txBit = 0; state = 3; slaveLow = ((txByte >> 7) & 1) == 0; }
			else { state = 0; slaveLow = false; }
		}
	}
}

// ---------------------------------------------------------------- SPI 95xxx (mode 0)
class SpiSim : ChipSim
{
	public byte[] Mem; int page; int busy; bool wel;
	int prevSck, prevCs = 1;
	int shift, bits, state, cmd, addr, addrBytesGot; int outByte, outBit; int miso;
	List<(int, byte)> pend = new List<(int, byte)>();
	public SpiSim(int size, int page) { Mem = new byte[size]; for (int i = 0; i < size; i++) Mem[i] = 0xFF; this.page = page; }
	public override byte Update(byte m)
	{
		int sck = m & 1, mosi = (m >> 1) & 1, cs = (m >> 3) & 1;
		if (cs == 1) { if (prevCs == 0) Deselect(); state = 0; bits = 0; shift = 0; miso = 1; }
		else
		{
			if (prevCs == 1) { state = 0; bits = 0; shift = 0; pend.Clear(); }
			if (prevSck == 0 && sck == 1) { shift = ((shift << 1) | mosi) & 0xFF; bits++; if (bits == 8) { Byte(shift); bits = 0; shift = 0; } }
			if (prevSck == 1 && sck == 0 && state == 9) { miso = (outByte >> (7 - outBit)) & 1; outBit++; if (outBit == 8) { outBit = 0; NextOut(); } }
		}
		prevSck = sck; prevCs = cs;
		byte o = m; o = (byte)((o & ~4) | (miso << 2)); return o;
	}
	void NextOut() { if (cmd == 5) outByte = (wel ? 2 : 0) | (busy > 0 ? 1 : 0); else { addr = (addr + 1) % Mem.Length; outByte = Mem[addr]; } }
	void Byte(int b)
	{
		if (state == 0) { cmd = b; addrBytesGot = 0; addr = 0; if (cmd == 6) { wel = true; state = 8; } else if (cmd == 5) { outByte = (wel ? 2 : 0) | (busy > 0 ? 1 : 0); if (busy > 0) busy--; outBit = 0; state = 9; miso = 0; } else if (cmd == 3 || cmd == 2) state = 1; else state = 8; }
		else if (state == 1) { addr = (addr << 8) | b; addrBytesGot++; if (addrBytesGot == 2) { if (cmd == 3) { outByte = Mem[addr % Mem.Length]; outBit = 0; state = 9; } else state = 2; } }
		else if (state == 2) { pend.Add((addr, (byte)b)); int ps = addr - (addr % page); addr = ps + ((addr + 1 - ps) % page); }
	}
	void Deselect()
	{
		if (cmd == 2 && pend.Count > 0 && wel) { foreach (var (a, b) in pend) Mem[a % Mem.Length] = b; WriteOps++; wel = false; busy = 3; }
		pend.Clear();
	}
	public override byte Sample(byte last) { if (cmd == 5 && state == 9 && busy > 0 && prevCs == 0) { } return last; }
}

// ---------------------------------------------------------------- Microwire 93Cxx
class MwSim : ChipSim
{
	public ushort[] Words; public byte[] Bytes; bool x16; int addrBits; int unitBits;
	int prevClk, prevCs;
	int state; // 0 idle(cs low), 1 wait start, 2 op, 3 addr, 4 read data, 5 write data, 6 done
	int op, addr, got, wbits, wval; int dout = 1; int rdBit; int rdAddr;
	bool wen; bool busy; int polls; bool writePending; int pendAddr, pendVal;
	public MwSim(int sizeBytes, bool x16, int addrBits)
	{
		this.x16 = x16; this.addrBits = addrBits; unitBits = x16 ? 16 : 8;
		if (x16) { Words = new ushort[sizeBytes / 2]; for (int i = 0; i < Words.Length; i++) Words[i] = 0xFFFF; }
		else { Bytes = new byte[sizeBytes]; for (int i = 0; i < sizeBytes; i++) Bytes[i] = 0xFF; }
	}
	int Units => x16 ? Words.Length : Bytes.Length;
	int Get(int a) { return x16 ? Words[a % Units] : Bytes[a % Units]; }
	public override byte Update(byte m)
	{
		int clk = m & 1, di = (m >> 1) & 1, cs = (m >> 3) & 1;
		if (cs == 1 && prevCs == 0) { state = 1; got = 0; op = 0; addr = 0; dout = busy ? 0 : 1; polls = 0; }
		if (cs == 0 && prevCs == 1) { CsFall(); state = 0; dout = 1; }
		if (cs == 1 && prevClk == 0 && clk == 1) Rising(di);
		prevClk = clk; prevCs = cs;
		byte o = m; o = (byte)((o & ~4) | ((cs == 1 ? dout : 1) << 2)); return o;
	}
	public override byte Sample(byte last)
	{
		if (busy && prevCs == 1 && state == 1) { polls++; if (polls >= 3) { busy = false; dout = 1; } }
		byte o = last; return (byte)((o & ~4) | ((prevCs == 1 ? (busy ? 0 : dout) : 1) << 2));
	}
	void Rising(int di)
	{
		if (state == 1) { if (di == 1) { state = 2; got = 0; } return; }
		if (state == 2) { op = (op << 1) | di; got++; if (got == 2) { state = 3; got = 0; addr = 0; } return; }
		if (state == 3)
		{
			addr = (addr << 1) | di; got++;
			if (got == addrBits)
			{
				if (op == 2) { state = 4; rdAddr = addr % Units; rdBit = unitBits; dout = 0; }
				else if (op == 1) { state = 5; wbits = 0; wval = 0; pendAddr = addr; }
				else { state = 6; pendAddr = addr; }
			}
			return;
		}
		if (state == 4)
		{
			rdBit--; dout = (Get(rdAddr) >> rdBit) & 1;
			if (rdBit == 0) { rdAddr = (rdAddr + 1) % Units; rdBit = unitBits; }
			return;
		}
		if (state == 5) { wval = (wval << 1) | di; wbits++; if (wbits == unitBits) { writePending = true; pendVal = wval; state = 6; } }
	}
	void CsFall()
	{
		if (state == 6 || state == 5)
		{
			if (writePending && wen) { if (x16) Words[pendAddr % Units] = (ushort)pendVal; else Bytes[pendAddr % Units] = (byte)pendVal; busy = true; polls = 0; WriteOps++; }
			writePending = false;
			if (op == 0 && state == 6) { int top = (pendAddr >> (addrBits - 2)) & 3; if (top == 3) wen = true; else if (top == 0) wen = false; }
		}
	}
}

static class Program
{
	static int fails;
	static void Check(bool ok, string what) { if (!ok) { fails++; Console.WriteLine("FAIL: " + what); } else Console.WriteLine("ok:   " + what); }

	static (FakeFtdi, ChipSim) Make(ChipInfo c, bool x16)
	{
		ChipSim sim;
		if (c.Family == "Microwire") sim = new MwSim(c.Size, x16, x16 ? c.Mw16 : c.Mw8);
		else if (c.Family == "SPI") sim = new SpiSim(c.Size, c.Page);
		else sim = new I2cSim(c.Size, c.Page, c.Family == "I2C1" ? 1 : 2);
		return (new FakeFtdi(sim), sim);
	}

	static void Main()
	{
		var rnd = new Random(7);
		foreach (var chip in Chips.All)
		{
			foreach (bool x16 in chip.Family == "Microwire" ? new[] { true, false } : new[] { true })
			foreach (bool swap in (chip.Family == "Microwire" && x16) ? new[] { false, true } : new[] { false })
			{
				string label = chip.Name + (chip.Family == "Microwire" ? (x16 ? " x16" : " x8") + (swap ? " swap" : "") : "");
				try
				{
					var (port, sim) = Make(chip, x16);
					var o = new ProgramOptions { X16 = x16, SwapBytes = swap, Repeat = 1 };
					var prog = new EepromProgrammer(port, chip, o, null, null);
					var blank = prog.Read();
					bool allFF = true; foreach (var b in blank) if (b != 0xFF) allFF = false;
					Check(blank.Length == chip.Size && allFF, label + ": read blank = FF");
					var data = new byte[chip.Size]; rnd.NextBytes(data);
					var prog2 = new EepromProgrammer(port, chip, o, null, null);
					prog2.Write(data, blank);
					var back = new EepromProgrammer(port, chip, o, null, null).Read();
					Check(EepromProgrammer.FirstDifference(data, back) == -1, label + ": write + read back identical");
					int opsAfterFirst = sim.WriteOps;
					var data2 = (byte[])data.Clone(); data2[3] ^= 0x55; data2[chip.Size - 2] ^= 0x0F;
					new EepromProgrammer(port, chip, o, null, null).Write(data2, back);
					var back2 = new EepromProgrammer(port, chip, o, null, null).Read();
					Check(EepromProgrammer.FirstDifference(data2, back2) == -1, label + ": partial rewrite identical");
					int ops2 = sim.WriteOps - opsAfterFirst;
					Check(ops2 > 0 && ops2 <= 4, label + ": only changed units written (" + ops2 + " write ops)");
				}
				catch (Exception e) { fails++; Console.WriteLine("FAIL: " + label + " threw " + e.GetType().Name + ": " + e.Message); }
			}
		}
		// word order check: x16 chip without swap exposes [hi, lo]
		{
			var chip = Chips.Find("93C66"); var (port, sim) = Make(chip, true); var ms = (MwSim)sim; ms.Words[0] = 0x1234; ms.Words[1] = 0xABCD;
			var d = new EepromProgrammer(port, chip, new ProgramOptions { X16 = true, Repeat = 1 }, null, null).Read();
			Check(d[0] == 0x12 && d[1] == 0x34 && d[2] == 0xAB && d[3] == 0xCD, "93C66 x16 word 0x1234 reads as 12 34");
			var (port2, sim2) = Make(chip, true); ((MwSim)sim2).Words[0] = 0x1234;
			var d2 = new EepromProgrammer(port2, chip, new ProgramOptions { X16 = true, SwapBytes = true, Repeat = 1 }, null, null).Read();
			Check(d2[0] == 0x34 && d2[1] == 0x12, "93C66 x16 swap reads as 34 12");
		}
		// no chip connected
		{
			try { var port = new FakeFtdi(null); var prog = new EepromProgrammer(port, Chips.Find("24C64"), new ProgramOptions { Repeat = 1 }, null, null); prog.Read(); Check(false, "no chip: should throw"); }
			catch (ProgrammerException e) { Check(e.Message.Contains("No response"), "no chip on I2C -> friendly error"); }
		}
		// wrong size
		{
			var chip = Chips.Find("24C64"); var (port, sim) = Make(chip, true);
			try { new EepromProgrammer(port, chip, new ProgramOptions { Repeat = 1 }, null, null).Write(new byte[100], null); Check(false, "size: should throw"); }
			catch (ProgrammerException e) { Check(e.Message.Contains("holds"), "wrong data size rejected"); }
		}
		// ---- automatic chip detection ("press Read") ----
		foreach (string name in new[] { "24C32", "24C64", "24C128", "24C256", "24C512" })
		{
			var chip = Chips.Find(name); var (port, sim) = Make(chip, true); var i2 = (I2cSim)sim;
			rnd.NextBytes(i2.Mem);
			var res = AutoReader.Read(port, "ford", new ProgramOptions { Repeat = 1 }, (t, p) => { }, null);
			Check(res.Chip.Name == name && EepromProgrammer.FirstDifference(res.Data, i2.Mem) == -1, "auto: detects " + name + " and reads it");
		}
		{
			var chip = Chips.Find("24C256"); var (port, sim) = Make(chip, true);   // blank
			var res = AutoReader.Read(port, "ford", new ProgramOptions { Repeat = 1 }, (t, p) => { }, null);
			Check(res.Note.Contains("blank"), "auto: blank I2C chip -> warns that size is unknown");
		}
		foreach (bool x16 in new[] { true, false })
		{
			var chip = Chips.Find("93C66"); var (port, sim) = Make(chip, x16); var mw = (MwSim)sim;
			var pattern = new byte[512]; for (int i = 0; i < 512; i++) pattern[i] = 0xFF;
			for (int i = 0; i < 50; i++) { pattern[i * 2] = 0x10; pattern[i * 2 + 1] = 0x05; }
			if (x16) { for (int w = 0; w < 256; w++) mw.Words[w] = (ushort)((pattern[w * 2] << 8) | pattern[w * 2 + 1]); }
			else { for (int i = 0; i < 512; i++) mw.Bytes[i] = pattern[i]; }
			var res = AutoReader.Read(port, "isuzu", new ProgramOptions { Repeat = 1 }, (t, p) => { }, null);
			Check(res.Chip.Name == "93C66" && res.X16 == x16 && EepromProgrammer.FirstDifference(res.Data, pattern) == -1, "auto: Isuzu 93C66 wired " + (x16 ? "x16" : "x8") + " identified");
		}
		{
			try { AutoReader.Read(new FakeFtdi(null), "isuzu", new ProgramOptions { Repeat = 1 }, (t, p) => { }, null); Check(false, "auto: nothing connected should fail"); }
			catch (ProgrammerException e) { Check(e.Message.Contains("Could not identify"), "auto: nothing connected -> friendly error"); }
		}
		Console.WriteLine(fails == 0 ? "ALL PASSED" : fails + " FAILURES");
		Environment.Exit(fails == 0 ? 0 : 1);
	}
}
