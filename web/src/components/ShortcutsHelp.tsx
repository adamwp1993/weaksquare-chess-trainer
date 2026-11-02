import { Kbd, Modal, Table } from "@mantine/core";
import { SHORTCUTS } from "../state/shortcuts";

// The "?" list of keyboard shortcuts.
export function ShortcutsHelp({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  return (
    <Modal opened={opened} onClose={onClose} title="Keyboard shortcuts">
      <Table data-testid="shortcuts-list">
        <Table.Tbody>
          {SHORTCUTS.map((s) => (
            <Table.Tr key={s.keys}>
              <Table.Td style={{ whiteSpace: "nowrap" }}>
                <Kbd>{s.keys}</Kbd>
              </Table.Td>
              <Table.Td>{s.action}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Modal>
  );
}
