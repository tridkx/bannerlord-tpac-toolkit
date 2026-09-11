using System;
using Half = SystemHalf.Half;
namespace MbTool {
  public static class HalfCheck {
    public static void Run() {
      float[] tests = {0f, 1f, -1f, 0.5f, 1.4578f, -0.7142f, 0.0891f, 100f, 1714f, 0.0001f};
      foreach (var f in tests) {
        Half h = (Half) f;
        float back = (float) h;
        ushort bits = Half.GetBits(h);
        Console.WriteLine($"  {f,12:G6} -> half bits 0x{bits:X4} -> {back,12:G6}   err={Math.Abs(back-f):G3}");
      }
    }
  }
}
