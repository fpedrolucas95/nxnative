// Mac: raw HID gamepads that GameController does not list (pad_hid.h, GitHub issue #637), read on the main run loop alongside front_mac.m's GameController players.
// Each device takes a player slot as a GameController controller does; front_mac.m defines the slot side (hidpad_attach / hidpad_detach / hidpad_read).
// Skipped, so no controller is read twice: GameController's synthetic devices, and every device GameController says it will list itself (+[GCController supportsHIDDevice:]:
// Xbox, PlayStation, Switch and MFi pads of any vendor) unless it lists none for the device within HIDPAD_GC_GRACE_MS (hidpad_found). DM_HID_PADS=0 turns this off,
// DM_HID_PADS=only reads every pad here and none through GameController.
#pragma once
#import <IOKit/hid/IOHIDManager.h>
#import <GameController/GameController.h>
#import <GameController/GCSyntheticDeviceKeys.h>
#include "pad_hid.h"
#include <stdio.h>
#include <stdlib.h>

typedef struct hid_pad { IOHIDDeviceRef hid; pad_hid st; char name[64]; int fallback; struct hid_pad *next; } hid_pad;   // fallback: a device GameController claimed but did not list
static IOHIDManagerRef g_hidpad_manager;
static hid_pad *g_hidpads;
static int g_hidpad_log, g_hidpad_only;
static void hidpad_attach(hid_pad *d);
static void hidpad_detach(hid_pad *d);
static void hidpad_read(hid_pad *d);

static void hidpad_value(void *ctx, IOReturn result, void *sender, IOHIDValueRef v) {
    (void)sender;
    hid_pad *d = ctx; if (result != kIOReturnSuccess) return;
    IOHIDElementRef e = IOHIDValueGetElement(v);
    uint32_t page = IOHIDElementGetUsagePage(e), usage = IOHIDElementGetUsage(e);
    CFIndex x = IOHIDValueGetIntegerValue(v), min = IOHIDElementGetLogicalMin(e), max = IOHIDElementGetLogicalMax(e);
    if (page == kHIDPage_Button && usage >= 1 && usage <= 32) {
        uint32_t bit = 1u << (usage - 1), was = d->st.buttons & bit;
        d->st.buttons = x ? d->st.buttons | bit : d->st.buttons & ~bit;
        if (g_hidpad_log && x && !was) LOG("[hid] %s: button usage %u", d->name, usage);
    } else if (page == kHIDPage_GenericDesktop && usage == kHIDUsage_GD_Hatswitch) {
        d->st.hat = pad_hid_hat(x, min, max);
    } else {
        int a = pad_hid_axis_of(page, usage); if (a < 0) return;
        d->st.axis[a] = pad_hid_norm(x, min, max);
    }
    hidpad_read(d);
}
// GameController lists a controller by the HID product name it reads from the device
static int hidpad_gc_lists(NSString *name) {
    for (GCController *c in GCController.controllers) if (c.extendedGamepad && [c.vendorName isEqualToString:name]) return 1;
    return 0;
}
static void hidpad_add(IOHIDDeviceRef hid, int fallback) {
    for (hid_pad *d = g_hidpads; d; d = d->next) if (d->hid == hid) return;
    NSNumber *vendor = (__bridge NSNumber *)IOHIDDeviceGetProperty(hid, CFSTR(kIOHIDVendorIDKey)), *product = (__bridge NSNumber *)IOHIDDeviceGetProperty(hid, CFSTR(kIOHIDProductIDKey));
    int vid = vendor.intValue, pid = product.intValue;
    hid_pad *d = calloc(1, sizeof *d); if (!d) { LOG("[RED] HID gamepad: cannot allocate device state"); return; }
    pad_hid_init(&d->st, getenv("DM_HID_MAP"));
    NSString *name = (__bridge NSString *)IOHIDDeviceGetProperty(hid, CFSTR(kIOHIDProductKey));
    snprintf(d->name, sizeof d->name, "%s", name.UTF8String ?: "HID gamepad");
    d->fallback = fallback;
    NSArray *els = CFBridgingRelease(IOHIDDeviceCopyMatchingElements(hid, NULL, kIOHIDOptionsTypeNone));
    for (id o in els) { IOHIDElementRef e = (__bridge IOHIDElementRef)o; int a = pad_hid_axis_of(IOHIDElementGetUsagePage(e), IOHIDElementGetUsage(e)); if (a >= 0) d->st.has[a] = 1; }
    d->hid = (IOHIDDeviceRef)CFRetain(hid); d->next = g_hidpads; g_hidpads = d;
    IOHIDDeviceRegisterInputValueCallback(hid, hidpad_value, d);
    hidpad_attach(d);
    // HID has no standard button numbering: the default map is 8BitDo's, so another vendor's pad may have its buttons in other places
    if (vid != PAD_HID_DEFAULT_VENDOR && !getenv("DM_HID_MAP"))
        LOG("controller '%s' (HID, %04x:%04x): buttons use 8BitDo's numbering; if they are in the wrong places, DM_HID_LOG=1 logs each button's number for a DM_HID_MAP", d->name, vid, pid);
}
// GameController's own controllers are skipped here, so no controller is read twice (+[GCController supportsHIDDevice:]). But a device it claims may never get a
// GCController: the 8BitDo Ultimate 2C Wired (2dc8:301d) on macOS 27 has supportsHIDDevice YES and GCController.controllers stays empty, so the game had no controller
// unless DM_HID_PADS=only was set. Such a device is read directly once GameController has listed no controller by its name HIDPAD_GC_GRACE_MS after it appeared;
// if GameController lists it later, it yields (hidpad_yield_to_gc)
enum { HIDPAD_GC_GRACE_MS = 2000 };
static void hidpad_found(void *ctx, IOReturn result, void *sender, IOHIDDeviceRef hid) {
    (void)ctx; (void)sender;
    if (result != kIOReturnSuccess || IOHIDDeviceGetProperty(hid, CFSTR(kIOHIDGCSyntheticDeviceKey)) == kCFBooleanTrue) return;
    for (hid_pad *d = g_hidpads; d; d = d->next) if (d->hid == hid) return;
    if (!g_hidpad_only && [GCController supportsHIDDevice:hid]) {   // front_mac.m reads it through its GCController (once per device: the call is not cheap)
        CFRetain(hid);
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)HIDPAD_GC_GRACE_MS * NSEC_PER_MSEC), dispatch_get_main_queue(), ^{
            NSString *name = (__bridge NSString *)IOHIDDeviceGetProperty(hid, CFSTR(kIOHIDProductKey));
            CFSetRef now = g_hidpad_manager ? IOHIDManagerCopyDevices(g_hidpad_manager) : NULL;
            int present = now && CFSetContainsValue(now, hid);
            if (now) CFRelease(now);
            if (present && !hidpad_gc_lists(name ?: @"")) {
                LOG("controller '%s': GameController supports it but listed no controller in %d ms, read directly (HID)", name.UTF8String ?: "?", HIDPAD_GC_GRACE_MS);
                hidpad_add(hid, 1);
            }
            CFRelease(hid);
        });
        return;
    }
    hidpad_add(hid, 0);
}
static void hidpad_removed(void *ctx, IOReturn result, void *sender, IOHIDDeviceRef hid) {
    (void)ctx; (void)result; (void)sender;
    hid_pad **link = &g_hidpads;
    while (*link && (*link)->hid != hid) link = &(*link)->next;
    if (!*link) return;
    hid_pad *d = *link; *link = d->next;
    IOHIDDeviceRegisterInputValueCallback(hid, NULL, NULL);
    hidpad_detach(d);
    CFRelease(d->hid); free(d);
}
// A device read directly because GameController listed nothing for it, now listed by GameController (front_mac.m calls this on every connect): its GCController plays instead
static void hidpad_yield_to_gc(void) {
    for (hid_pad **link = &g_hidpads; *link;) {
        hid_pad *d = *link;
        if (!d->fallback || !hidpad_gc_lists(@(d->name))) { link = &d->next; continue; }
        LOG("controller '%s': GameController lists it now, read through GameController", d->name);
        *link = d->next;
        IOHIDDeviceRegisterInputValueCallback(d->hid, NULL, NULL);
        hidpad_detach(d);
        CFRelease(d->hid); free(d);
    }
}
static void hidpad_start(void) {
    const char *e = getenv("DM_HID_PADS"); if (e && !strcmp(e, "0")) return;
    e = getenv("DM_HID_LOG"); g_hidpad_log = e && atoi(e);
    g_hidpad_manager = IOHIDManagerCreate(kCFAllocatorDefault, kIOHIDOptionsTypeNone); if (!g_hidpad_manager) return;
    IOHIDManagerSetDeviceMatchingMultiple(g_hidpad_manager, (__bridge CFArrayRef)@[
        @{@kIOHIDDeviceUsagePageKey: @(kHIDPage_GenericDesktop), @kIOHIDDeviceUsageKey: @(kHIDUsage_GD_GamePad)},
        @{@kIOHIDDeviceUsagePageKey: @(kHIDPage_GenericDesktop), @kIOHIDDeviceUsageKey: @(kHIDUsage_GD_Joystick)}]);
    IOHIDManagerRegisterDeviceMatchingCallback(g_hidpad_manager, hidpad_found, NULL);
    IOHIDManagerRegisterDeviceRemovalCallback(g_hidpad_manager, hidpad_removed, NULL);
    IOHIDManagerScheduleWithRunLoop(g_hidpad_manager, CFRunLoopGetMain(), kCFRunLoopCommonModes);
    IOReturn r = IOHIDManagerOpen(g_hidpad_manager, kIOHIDOptionsTypeNone);   // nonexclusive: GameController and other apps keep their devices
    if (r != kIOReturnSuccess) {
        LOG("[RED] HID gamepads: cannot open HID (0x%x); only GameController controllers are read", r);
        IOHIDManagerUnscheduleFromRunLoop(g_hidpad_manager, CFRunLoopGetMain(), kCFRunLoopCommonModes);
        CFRelease(g_hidpad_manager); g_hidpad_manager = NULL;
    }
}
