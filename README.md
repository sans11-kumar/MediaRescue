# MediaRescue V2 — Windows Photo & Video Signature Recovery

## Run
Install Python 3.11+ on Windows. In the extracted folder:

```
py -m pip install -r requirements.txt
py media_rescue_v2.py
```

Or run `build_windows.bat`, then open `dist\MediaRescueV2.exe` **as administrator** to access raw volumes.

## Workflow
1. **Stop using the affected drive immediately**. Do not install the application on it.
2. Ideally create a forensic raw disk image with an established imaging utility and scan the image (much safer).
3. Select a volume or raw `.img/.dd/.bin` disk image, then Start deep scan.
4. Select candidate images/videos; preview JPEG/PNG when possible.
5. Recover selected files to **another physical disk**.
6. Verify recovered files using a media viewer. Recovered files can be false positives or corrupt.

## Scope and limitations
- Raw contiguous-data signature carving for JPEG, PNG, MP4, MOV; it is **not** an NTFS $MFT metadata recovery tool.
- It does not determine whether candidates are deleted or currently allocated: both can appear.
- Fragmented/overwritten files may be incomplete or corrupted. MP4/MOV box sizes must be valid and the file must be contiguous; files with 0-length final boxes and some valid container arrangements may be skipped.
- Does not recover missing blocks, deleted cloud data, encrypted content or overwritten data. SSD TRIM often makes recovery impossible.
- Raw logical volume scanning excludes unallocated space outside the volume and cannot bypass BitLocker encryption; unlock first.
- Running as administrator may be necessary. Some system volumes reject raw reads while Windows is using them; use an offline raw image for best results.
- MP4/MOV preview is not built in; recovered media can be opened separately.
- Drive-safety check prevents writing to the **same drive letter** when scanning a live volume, but cannot detect all cases where two drive letters map to the same physical disk. Always use a different **physical** disk.
- Scans can be slow on large storage; cancel at any time. No guarantee of recovered files.

## Privacy
Entirely local. No upload, telemetry, or network functionality.
