import { useState } from 'react';
import type { Contact, RawPacket, RadioConfig } from '../types';
import { PacketVisualizer } from './PacketVisualizer';
import { RawPacketList } from './RawPacketList';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';
import { cn } from '@/lib/utils';

interface VisualizerViewProps {
  packets: RawPacket[];
  contacts: Contact[];
  config: RadioConfig | null;
  onClearPackets?: () => void;
}

export function VisualizerView({ packets, contacts, config, onClearPackets }: VisualizerViewProps) {
  const [fullScreen, setFullScreen] = useState(false);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex justify-between items-center px-4 py-3 border-b border-border font-medium text-lg">
        <span>Mesh Visualizer</span>
      </div>

      {/* Mobile: Tabbed interface */}
      <div className="flex-1 overflow-hidden md:hidden">
        <Tabs defaultValue="visualizer" className="h-full flex flex-col">
          <TabsList className="mx-4 mt-2 grid grid-cols-2">
            <TabsTrigger value="visualizer">Visualizer</TabsTrigger>
            <TabsTrigger value="packets">Packet Feed</TabsTrigger>
          </TabsList>
          <TabsContent value="visualizer" className="flex-1 m-0 overflow-hidden">
            <PacketVisualizer
              packets={packets}
              contacts={contacts}
              config={config}
              onClearPackets={onClearPackets}
            />
          </TabsContent>
          <TabsContent value="packets" className="flex-1 m-0 overflow-hidden">
            <RawPacketList packets={packets} />
          </TabsContent>
        </Tabs>
      </div>

      {/* Desktop: Split screen (or full screen if toggled) */}
      <div className="hidden md:flex flex-1 overflow-hidden">
        {/* Visualizer panel */}
        <div
          className={cn(
            'overflow-hidden transition-all duration-200',
            fullScreen ? 'flex-1' : 'flex-1 border-r border-border'
          )}
        >
          <PacketVisualizer
            packets={packets}
            contacts={contacts}
            config={config}
            fullScreen={fullScreen}
            onFullScreenChange={setFullScreen}
            onClearPackets={onClearPackets}
          />
        </div>

        {/* Packet feed panel - hidden when full screen */}
        <div
          className={cn(
            'overflow-hidden transition-all duration-200',
            fullScreen ? 'w-0' : 'w-[31rem] lg:w-[38rem]'
          )}
        >
          <div className="h-full flex flex-col">
            <div className="px-3 py-2 border-b border-border text-sm font-medium text-muted-foreground">
              Packet Feed
            </div>
            <div className="flex-1 overflow-hidden">
              <RawPacketList packets={packets} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
