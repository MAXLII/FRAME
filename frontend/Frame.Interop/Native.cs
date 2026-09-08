using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace Frame.Interop;

public sealed class BackendHandle : SafeHandleZeroOrMinusOneIsInvalid
{
    public BackendHandle() : base(true) { }
    protected override bool ReleaseHandle() { Native.Destroy(handle); return true; }
}

public static class Native
{
    private const string Dll = "frame_backend.dll";
    [DllImport(Dll, EntryPoint="frame_abi_version", CallingConvention=CallingConvention.Cdecl)] public static extern uint Version();
    [DllImport(Dll, EntryPoint="frame_create", CallingConvention=CallingConvention.Cdecl)] public static extern BackendHandle Create();
    [DllImport(Dll, EntryPoint="frame_destroy", CallingConvention=CallingConvention.Cdecl)] internal static extern void Destroy(nint handle);
    [DllImport(Dll, EntryPoint="frame_submit", CallingConvention=CallingConvention.Cdecl)] public static extern int Submit(BackendHandle handle, byte[] command, uint size, out ulong id);
    [DllImport(Dll, EntryPoint="frame_result", CallingConvention=CallingConvention.Cdecl)] public static extern int Result(BackendHandle handle, ulong id, [Out] byte[]? buffer, uint capacity, out uint needed);
    [DllImport(Dll, EntryPoint="frame_cancel", CallingConvention=CallingConvention.Cdecl)] public static extern int Cancel(BackendHandle handle, ulong id);
    [DllImport(Dll, EntryPoint="frame_release", CallingConvention=CallingConvention.Cdecl)] public static extern int Release(BackendHandle handle, ulong id);
    [DllImport(Dll, EntryPoint="frame_snapshot", CallingConvention=CallingConvention.Cdecl)] public static extern int Snapshot(BackendHandle handle, [Out] byte[]? buffer, uint capacity, out uint needed);
    [DllImport(Dll, EntryPoint="frame_events", CallingConvention=CallingConvention.Cdecl)] public static extern int Events(BackendHandle handle, ulong after, uint limit, [Out] byte[]? buffer, uint capacity, out uint needed);
}
