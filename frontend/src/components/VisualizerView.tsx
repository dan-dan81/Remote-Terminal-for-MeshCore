import { useState } from 'react';
import type { Contact, RawPacket, Channel, RadioConfig } from '../types';
import { PacketVisualizer } from './PacketVisualizer';
import { RawPacketList } from './RawPacketList';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';
import { Checkbox } from './ui/checkbox';
import { cn } from '@/lib/utils';

interface VisualizerViewProps {
  packets: RawPacket[];
  contacts: Contact[];
  channels: Channel[];
  config: RadioConfig | null;
}

export function VisualizerView({ packets, contacts, channels, config }: VisualizerViewProps) {
  const [fullScreen, setFullScreen] = useState(false);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex justify-between items-center px-4 py-3 border-b border-border font-medium text-lg">
        <span>Mesh Visualizer</span>
        {/* Full screen toggle - only show on larger screens */}
        <label className="hidden md:flex items-center gap-2 text-sm font-normal cursor-pointer">
          <Checkbox
            checked={fullScreen}
            onCheckedChange={(checked) => setFullScreen(checked === true)}
          />
          <span>Full screen</span>
        </label>
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
              channels={channels}
              config={config}
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
            channels={channels}
            config={config}
          />
        </div>

        {/* Packet feed panel - hidden when full screen */}
        <div
          className={cn(
            'overflow-hidden transition-all duration-200',
            fullScreen ? 'w-0' : 'w-[45rem] lg:w-[54rem]'
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
