import { useState } from 'react';
import type { HealthStatus } from '../types';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Button } from './ui/button';
import { toast } from './ui/sonner';
import { api } from '../api';

interface MaintenanceModalProps {
  open: boolean;
  health: HealthStatus | null;
  onClose: () => void;
  onHealthRefresh: () => Promise<void>;
}

export function MaintenanceModal({
  open,
  health,
  onClose,
  onHealthRefresh,
}: MaintenanceModalProps) {
  const [retentionDays, setRetentionDays] = useState('14');
  const [cleaning, setCleaning] = useState(false);
  const [deduping, setDeduping] = useState(false);

  const handleCleanup = async () => {
    const days = parseInt(retentionDays, 10);
    if (isNaN(days) || days < 1) {
      toast.error('Invalid retention days', {
        description: 'Retention days must be at least 1',
      });
      return;
    }

    setCleaning(true);

    try {
      const result = await api.runMaintenance(days);
      toast.success('Database cleanup complete', {
        description: `Deleted ${result.packets_deleted} old packet${result.packets_deleted === 1 ? '' : 's'}`,
      });
      // Refresh health to get updated database size
      await onHealthRefresh();
    } catch (err) {
      console.error('Failed to run maintenance:', err);
      toast.error('Database cleanup failed', {
        description: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setCleaning(false);
    }
  };

  const handleDedup = async () => {
    setDeduping(true);

    try {
      const result = await api.deduplicatePackets();
      if (result.started) {
        toast.success('Deduplication started', {
          description: result.message,
        });
      } else {
        toast.info('Deduplication', {
          description: result.message,
        });
      }
    } catch (err) {
      console.error('Failed to start deduplication:', err);
      toast.error('Deduplication failed', {
        description: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setDeduping(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="sm:max-w-[400px]">
        <DialogHeader>
          <DialogTitle>Database Maintenance</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Current database size: <span className="font-medium">{health?.database_size_mb ?? '?'} MB</span>
          </p>

          <div className="space-y-3">
            <Label>Cleanup Old Packets</Label>
            <p className="text-xs text-muted-foreground">
              Delete undecrypted packets older than the specified days. This helps manage storage
              for packets that couldn't be decrypted (unknown channel keys).
            </p>
            <div className="flex gap-2 items-end">
              <div className="space-y-1">
                <Label htmlFor="retention-days" className="text-xs">Days to retain</Label>
                <Input
                  id="retention-days"
                  type="number"
                  min="1"
                  max="365"
                  value={retentionDays}
                  onChange={(e) => setRetentionDays(e.target.value)}
                  className="w-20"
                />
              </div>
              <Button
                variant="outline"
                onClick={handleCleanup}
                disabled={cleaning}
              >
                {cleaning ? 'Cleaning...' : 'Cleanup'}
              </Button>
            </div>
          </div>

          <div className="space-y-3">
            <Label>Remove Duplicate Packets</Label>
            <p className="text-xs text-muted-foreground">
              Remove packets with duplicate payloads (same message received via different paths).
              Runs in background and may take a long time.
            </p>
            <Button
              variant="outline"
              onClick={handleDedup}
              disabled={deduping}
            >
              {deduping ? 'Starting...' : 'Remove Duplicates'}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
