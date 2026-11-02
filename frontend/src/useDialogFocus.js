import { useEffect, useRef } from 'react';

/** Keep keyboard navigation inside a modal and restore the opening control. */
export function useDialogFocus(dialogRef, onClose, busy = false) {
  const close = useRef(onClose); close.current = onClose;
  const pending = useRef(busy); pending.current = busy;
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const previous = document.activeElement;
    const candidates = () => [...dialog.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),a[href],[tabindex="0"]')].filter(node => node.getClientRects().length && node.type !== 'hidden');
    (candidates()[0] || dialog).focus({ preventScroll: true });
    const keydown = event => {
      if (event.key === 'Escape') {
        event.preventDefault(); event.stopPropagation();
        if (!pending.current) close.current();
      } else if (event.key === 'Tab') {
        const items = candidates(), first = items[0], last = items.at(-1);
        if (!first) { event.preventDefault(); dialog.focus(); }
        else if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener('keydown', keydown, true);
    return () => {
      document.removeEventListener('keydown', keydown, true);
      if (previous?.isConnected) previous.focus({ preventScroll: true });
    };
  }, [dialogRef]);
}
