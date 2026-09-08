// SPDX-License-Identifier: MIT
// Freestanding ARM DWARF fixture. Never downloaded to a target.
struct Controller { float gain; int count; };
volatile float gain = 1.25f;
Controller controller{2.5f, 7};
Controller *active = &controller;
unsigned samples[3] = {1, 2, 3};
double precision_value = 1.23456789;
struct ListNode { unsigned value; ListNode *next; };
ListNode list_node{101, nullptr};
ListNode *list_head = &list_node;
Controller resolved_controller __attribute__((section(".resolved"))){3.5f, 9};
ListNode resolved_node __attribute__((section(".resolved_node"))){202, nullptr};
void *opaque_object = &resolved_controller;
unsigned char *byte_object = reinterpret_cast<unsigned char *>(&resolved_controller);
struct Registry { void *object; };
Registry registry{&resolved_controller};
extern "C" void fixture_entry() { for (;;) {} }
