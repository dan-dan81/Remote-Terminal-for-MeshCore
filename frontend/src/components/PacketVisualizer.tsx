import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  forceX,
  forceY,
  type Simulation,
  type SimulationNodeDatum,
  type SimulationLinkDatum,
} from 'd3-force';
import { MeshCoreDecoder, PayloadType } from '@michaelhart/meshcore-decoder';
import type { Contact, RawPacket, Channel, RadioConfig } from '../types';
import { CONTACT_TYPE_REPEATER } from '../utils/contactAvatar';
import { Checkbox } from './ui/checkbox';

// Node types for visualization
type NodeType = 'self' | 'repeater' | 'client';

interface GraphNode extends SimulationNodeDatum {
  id: string;
  name: string | null;
  type: NodeType;
  isAmbiguous: boolean;
  lastActivity: number;
  lastSeen?: number | null; // Contact's last_seen timestamp from backend
  ambiguousNames?: string[];
  // D3 simulation adds these - redeclare for convenience
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number | null;
  fy?: number | null;
}

interface GraphLink extends SimulationLinkDatum<GraphNode> {
  source: string | GraphNode;
  target: string | GraphNode;
  lastActivity: number;
}

// Packet type labels
type PacketLabel = 'AD' | 'GT' | 'DM' | '?';

// Animated particle
interface Particle {
  linkKey: string;
  progress: number; // 0 to 1
  speed: number;
  color: string;
  label: PacketLabel;
  // Track actual source/target for correct direction
  fromNodeId: string;
  toNodeId: string;
}

// A single observed path for a packet
interface ObservedPath {
  nodes: string[]; // Node IDs from origin to 'self'
  snr: number | null; // Signal quality (for potential visual feedback)
  timestamp: number; // When this path was observed
}

// Aggregated packet entry during observation window
interface PendingPacket {
  key: string; // Unique identifier
  label: PacketLabel; // 'AD' | 'GT' | 'DM' | '?'
  originNodeId: string | null; // Full origin node ID (when known)
  paths: ObservedPath[]; // All observed paths
  firstSeen: number; // When first packet arrived
  expiresAt: number; // When observation window closes (firstSeen + 5000ms)
}

interface PacketVisualizerProps {
  packets: RawPacket[];
  contacts: Contact[];
  channels: Channel[];
  config: RadioConfig | null;
}

// Colors
const COLORS = {
  self: '#22c55e',
  repeater: '#f59e0b',
  client: '#3b82f6',
  ambiguous: '#9ca3af',
  link: '#4b5563',
  linkActive: '#6b7280',
  particle: '#f59e0b',
  background: '#0a0a0a',
  // Particle colors by type
  particleAD: '#f59e0b', // Orange for advertisements
  particleGT: '#06b6d4', // Cyan for group text (distinct from green self)
  particleDM: '#8b5cf6', // Purple for direct messages
  particleUnknown: '#6b7280', // Gray for unknown
};

// Parse result from decoder
interface ParsedPacket {
  routeType: number;
  payloadType: number;
  pathBytes: string[];
  srcHash: string | null;
  dstHash: string | null;
  advertPubkey: string | null;
  groupTextSender: string | null;
}

function parsePacket(hexData: string): ParsedPacket | null {
  try {
    const decoded = MeshCoreDecoder.decode(hexData);
    if (!decoded.isValid) return null;

    const result: ParsedPacket = {
      routeType: decoded.routeType,
      payloadType: decoded.payloadType,
      pathBytes: decoded.path || [],
      srcHash: null,
      dstHash: null,
      advertPubkey: null,
      groupTextSender: null,
    };

    if (decoded.payloadType === PayloadType.TextMessage && decoded.payload.decoded) {
      const payload = decoded.payload.decoded as {
        sourceHash?: string;
        destinationHash?: string;
      };
      result.srcHash = payload.sourceHash || null;
      result.dstHash = payload.destinationHash || null;
    } else if (decoded.payloadType === PayloadType.Advert && decoded.payload.decoded) {
      const payload = decoded.payload.decoded as { publicKey?: string };
      result.advertPubkey = payload.publicKey || null;
    } else if (decoded.payloadType === PayloadType.GroupText && decoded.payload.decoded) {
      const payload = decoded.payload.decoded as {
        decrypted?: { sender?: string };
      };
      result.groupTextSender = payload.decrypted?.sender || null;
    }

    return result;
  } catch {
    return null;
  }
}

// Simple hash function for content identity
function simpleHash(str: string): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = (hash << 5) - hash + char;
    hash = hash & hash; // Convert to 32bit integer
  }
  return Math.abs(hash).toString(16).padStart(8, '0');
}

// Get packet label from payload type
function getPacketLabel(payloadType: number): PacketLabel {
  if (payloadType === PayloadType.Advert) return 'AD';
  if (payloadType === PayloadType.GroupText) return 'GT';
  if (payloadType === PayloadType.TextMessage) return 'DM';
  return '?';
}

// Generate unique key for grouping packet repeats
function generatePacketKey(parsed: ParsedPacket, rawPacket: RawPacket): string {
  // For adverts: use publicKey prefix (12 chars)
  if (parsed.payloadType === PayloadType.Advert && parsed.advertPubkey) {
    return `ad:${parsed.advertPubkey.slice(0, 12)}`;
  }

  // For group text: channel + sender + content hash
  if (parsed.payloadType === PayloadType.GroupText) {
    const sender = parsed.groupTextSender || rawPacket.decrypted_info?.sender || '?';
    const channelKey = rawPacket.decrypted_info?.channel_name || '?';
    // Use first 8 chars of data hash for content identity
    const contentHash = simpleHash(rawPacket.data).slice(0, 8);
    return `gt:${channelKey}:${sender}:${contentHash}`;
  }

  // For DMs: src + dst + content hash
  if (parsed.payloadType === PayloadType.TextMessage) {
    const contentHash = simpleHash(rawPacket.data).slice(0, 8);
    return `dm:${parsed.srcHash || '?'}:${parsed.dstHash || '?'}:${contentHash}`;
  }

  // For other packets: use full data hash
  return `other:${simpleHash(rawPacket.data)}`;
}

// Helper functions for contact matching
function matchPrefixToContact(hexPrefix: string, contacts: Contact[]): Contact | null {
  const normalizedPrefix = hexPrefix.toLowerCase();
  const matches = contacts.filter((c) => c.public_key.toLowerCase().startsWith(normalizedPrefix));
  return matches.length === 1 ? matches[0] : null;
}

function getAllMatchingContacts(hexPrefix: string, contacts: Contact[]): Contact[] {
  const normalizedPrefix = hexPrefix.toLowerCase();
  return contacts.filter((c) => c.public_key.toLowerCase().startsWith(normalizedPrefix));
}

function createAmbiguousNodeId(hexPrefix: string): string {
  return `?${hexPrefix.toLowerCase()}`;
}

const MAX_LINKS = 100;

// Constants for particle animation
const PARTICLE_SPEED = 0.008;
// Observation window for aggregating multi-path packets
const OBSERVATION_WINDOW_MS = 2000;

export function PacketVisualizer({ packets, contacts, config }: PacketVisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const processedPacketsRef = useRef<Set<number>>(new Set());

  // Options
  const [showAmbiguousPaths, setShowAmbiguousPaths] = useState(true);
  const [showAmbiguousNodes, setShowAmbiguousNodes] = useState(false);
  const [chargeStrength, setChargeStrength] = useState(-200);
  const [filterOldRepeaters, setFilterOldRepeaters] = useState(false);

  // Graph data
  const nodesMapRef = useRef<Map<string, GraphNode>>(new Map());
  const linksMapRef = useRef<Map<string, GraphLink>>(new Map());

  // D3 simulation
  const simulationRef = useRef<Simulation<GraphNode, GraphLink> | null>(null);

  // Particles for animation
  const particlesRef = useRef<Particle[]>([]);

  // Pending packets in observation window (waiting for more paths)
  const pendingPacketsRef = useRef<Map<string, PendingPacket>>(new Map());

  // Timers for per-packet observation windows
  const packetTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  // Animation frame
  const animationFrameRef = useRef<number>(0);

  // Pan and zoom state
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const isDraggingRef = useRef(false);
  const lastMousePosRef = useRef({ x: 0, y: 0 });

  // Hover state for showing full ambiguous names
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  // Debug stats
  const [debugStats, setDebugStats] = useState({
    processed: 0,
    animated: 0,
    nodes: 0,
    links: 0,
  });

  // Track dimensions
  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        setDimensions({ width: rect.width, height: rect.height });
      }
    };

    updateDimensions();
    const resizeObserver = new ResizeObserver(updateDimensions);
    if (containerRef.current) {
      resizeObserver.observe(containerRef.current);
    }
    return () => resizeObserver.disconnect();
  }, []);

  // Initialize simulation
  useEffect(() => {
    const simulation = forceSimulation<GraphNode, GraphLink>([])
      .force(
        'link',
        forceLink<GraphNode, GraphLink>([])
          .id((d) => d.id)
          .distance(80)
          .strength(0.3) // Weaker link force so repulsion can spread nodes
      )
      .force(
        'charge',
        forceManyBody<GraphNode>()
          .strength((d) => (d.id === 'self' ? -1200 : -200)) // Self node has 6x repulsion
          .distanceMax(500)
      )
      .force('center', forceCenter(dimensions.width / 2, dimensions.height / 2))
      .force('collide', forceCollide(40)) // Slightly larger collision radius
      // Keep self node near center with gentle force
      .force(
        'selfX',
        forceX<GraphNode>(dimensions.width / 2).strength((d) => (d.id === 'self' ? 0.1 : 0))
      )
      .force(
        'selfY',
        forceY<GraphNode>(dimensions.height / 2).strength((d) => (d.id === 'self' ? 0.1 : 0))
      )
      .alphaDecay(0.02) // Moderate decay for settling
      .velocityDecay(0.5) // Higher damping for calmer movement
      .alphaTarget(0.03); // Never fully settle - always gently adjusting

    simulationRef.current = simulation;

    return () => {
      simulation.stop();
    };
  }, []);

  // Update simulation center when dimensions change
  useEffect(() => {
    if (simulationRef.current) {
      simulationRef.current.force(
        'center',
        forceCenter(dimensions.width / 2, dimensions.height / 2)
      );
      simulationRef.current.force(
        'selfX',
        forceX<GraphNode>(dimensions.width / 2).strength((d) => (d.id === 'self' ? 0.1 : 0))
      );
      simulationRef.current.force(
        'selfY',
        forceY<GraphNode>(dimensions.height / 2).strength((d) => (d.id === 'self' ? 0.1 : 0))
      );
      simulationRef.current.alpha(0.3).restart();
    }
  }, [dimensions]);

  // Update charge strength when slider changes
  useEffect(() => {
    if (simulationRef.current) {
      simulationRef.current.force(
        'charge',
        forceManyBody<GraphNode>()
          .strength((d) => (d.id === 'self' ? chargeStrength * 6 : chargeStrength)) // Self node has 6x repulsion
          .distanceMax(500)
      );
      simulationRef.current.alpha(0.5).restart();
    }
  }, [chargeStrength]);

  // Reset graph when display options change (to reprocess packets with new settings)
  useEffect(() => {
    // Clear processed packets to force reprocessing
    processedPacketsRef.current.clear();

    // Clear nodes except 'self'
    const selfNode = nodesMapRef.current.get('self');
    nodesMapRef.current.clear();
    if (selfNode) {
      nodesMapRef.current.set('self', selfNode);
    }

    // Clear links
    linksMapRef.current.clear();

    // Clear particles and pending packets
    particlesRef.current = [];
    pendingPacketsRef.current.clear();

    // Clear all pending timers
    for (const timer of packetTimersRef.current.values()) {
      clearTimeout(timer);
    }
    packetTimersRef.current.clear();

    // Update stats
    setDebugStats((prev) => ({
      ...prev,
      processed: 0,
      animated: 0,
      nodes: selfNode ? 1 : 0,
      links: 0,
    }));
  }, [showAmbiguousPaths, showAmbiguousNodes]);

  // Helper to update simulation with current data
  const updateSimulation = useCallback(() => {
    if (!simulationRef.current) return;

    const nodes = Array.from(nodesMapRef.current.values());
    const allLinks = Array.from(linksMapRef.current.values());
    const links = allLinks.length > MAX_LINKS ? allLinks.slice(-MAX_LINKS) : allLinks;

    // Update nodes - preserve positions for existing nodes
    simulationRef.current.nodes(nodes);

    // Update links
    const linkForce = simulationRef.current.force('link') as ReturnType<
      typeof forceLink<GraphNode, GraphLink>
    >;
    if (linkForce) {
      linkForce.links(links);
    }

    // Gently reheat simulation (low alpha = calmer adjustment)
    simulationRef.current.alpha(0.15).restart();

    setDebugStats((prev) => ({
      ...prev,
      nodes: nodes.length,
      links: links.length,
    }));
  }, []);

  // Ensure 'self' node exists
  useEffect(() => {
    const selfId = 'self';
    if (!nodesMapRef.current.has(selfId)) {
      nodesMapRef.current.set(selfId, {
        id: selfId,
        name: config?.name || 'Me',
        type: 'self',
        isAmbiguous: false,
        lastActivity: Date.now(),
        x: dimensions.width / 2,
        y: dimensions.height / 2,
      });
      updateSimulation();
    }
  }, [config, dimensions, updateSimulation]);

  // Helper to add/update a node
  const addOrUpdateNode = useCallback(
    (
      id: string,
      name: string | null,
      type: NodeType,
      isAmbiguous: boolean,
      ambiguousNames?: string[],
      lastSeen?: number | null
    ) => {
      const now = Date.now();
      const existing = nodesMapRef.current.get(id);
      if (existing) {
        existing.lastActivity = now;
        if (name && !existing.name) existing.name = name;
        if (ambiguousNames) existing.ambiguousNames = ambiguousNames;
        if (lastSeen !== undefined) existing.lastSeen = lastSeen;
      } else {
        // Position new nodes near self with slight random offset for calmer entry
        const selfNode = nodesMapRef.current.get('self');
        const baseX = selfNode?.x ?? 400;
        const baseY = selfNode?.y ?? 300;
        const offsetX = (Math.random() - 0.5) * 100;
        const offsetY = (Math.random() - 0.5) * 100;

        nodesMapRef.current.set(id, {
          id,
          name,
          type,
          isAmbiguous,
          lastActivity: now,
          lastSeen,
          ambiguousNames,
          x: baseX + offsetX,
          y: baseY + offsetY,
        });
      }
    },
    []
  );

  // Helper to add/update a link
  const addOrUpdateLink = useCallback((sourceId: string, targetId: string): string => {
    const now = Date.now();
    const linkKey = [sourceId, targetId].sort().join('->');
    const existing = linksMapRef.current.get(linkKey);
    if (existing) {
      existing.lastActivity = now;
    } else {
      linksMapRef.current.set(linkKey, {
        source: sourceId,
        target: targetId,
        lastActivity: now,
      });
    }
    return linkKey;
  }, []);

  // Publish a packet: spawn particles for all its paths simultaneously
  // Uses negative initial progress so particles flow continuously through nodes
  const publishPacket = useCallback((packetKey: string) => {
    const pending = pendingPacketsRef.current.get(packetKey);
    if (!pending) return;

    // Remove from pending and clear timer
    pendingPacketsRef.current.delete(packetKey);
    packetTimersRef.current.delete(packetKey);

    // Color map for particle types
    const colorMap: Record<PacketLabel, string> = {
      AD: COLORS.particleAD,
      GT: COLORS.particleGT,
      DM: COLORS.particleDM,
      '?': COLORS.particleUnknown,
    };
    const particleColor = colorMap[pending.label];

    // Spawn particles for ALL paths simultaneously
    // Each hop starts with negative progress so they flow continuously
    // Hop 0 starts at progress 0, hop 1 starts at -1, hop 2 starts at -2, etc.
    // This creates a smooth "train" effect as particles traverse the path
    for (const observedPath of pending.paths) {
      const path = observedPath.nodes.filter(
        (nodeId, i) => i === 0 || nodeId !== observedPath.nodes[i - 1]
      );
      if (path.length < 2) continue;

      for (let i = 0; i < path.length - 1; i++) {
        const fromNode = path[i];
        const toNode = path[i + 1];
        const linkKey = [fromNode, toNode].sort().join('->');

        // Start with negative progress: hop 0 at 0, hop 1 at -1, hop 2 at -2
        // Each particle becomes visible when progress >= 0
        particlesRef.current.push({
          linkKey,
          progress: -i, // Negative offset for continuous flow
          speed: PARTICLE_SPEED,
          color: particleColor,
          label: pending.label,
          fromNodeId: fromNode,
          toNodeId: toNode,
        });
      }
    }
  }, []);

  // Process new packets
  useEffect(() => {
    let newProcessed = 0;
    let newAnimated = 0;
    let needsUpdate = false;

    packets.forEach((packet) => {
      if (processedPacketsRef.current.has(packet.id)) return;
      processedPacketsRef.current.add(packet.id);
      newProcessed++;

      if (processedPacketsRef.current.size > 1000) {
        const ids = Array.from(processedPacketsRef.current);
        processedPacketsRef.current = new Set(ids.slice(-500));
      }

      const parsed = parsePacket(packet.data);
      if (!parsed) return;

      const myPubkeyPrefix = config?.public_key?.slice(0, 2).toLowerCase() || null;

      const addNodeFromPrefix = (
        hexPrefix: string,
        isRepeater: boolean,
        showAmbiguous: boolean
      ): string | null => {
        const contact = matchPrefixToContact(hexPrefix, contacts);
        if (contact) {
          const nodeId = contact.public_key.slice(0, 12).toLowerCase();
          const nodeType: NodeType = contact.type === CONTACT_TYPE_REPEATER ? 'repeater' : 'client';
          addOrUpdateNode(nodeId, contact.name, nodeType, false, undefined, contact.last_seen);
          needsUpdate = true;
          return nodeId;
        } else if (showAmbiguous) {
          const matchingContacts = getAllMatchingContacts(hexPrefix, contacts);
          const ambiguousId = createAmbiguousNodeId(hexPrefix);
          const filteredContacts = isRepeater
            ? matchingContacts.filter((c) => c.type === CONTACT_TYPE_REPEATER)
            : matchingContacts.filter((c) => c.type !== CONTACT_TYPE_REPEATER);
          const allNames = filteredContacts.map((c) => c.name || c.public_key.slice(0, 8));
          // Use most recent last_seen from matching contacts
          const mostRecentSeen = filteredContacts.reduce(
            (max, c) => (c.last_seen && (!max || c.last_seen > max) ? c.last_seen : max),
            null as number | null
          );
          const label = hexPrefix.toUpperCase();
          addOrUpdateNode(
            ambiguousId,
            label,
            isRepeater ? 'repeater' : 'client',
            true,
            allNames,
            mostRecentSeen
          );
          needsUpdate = true;
          return ambiguousId;
        }
        return null;
      };

      const addNodeFromPubkey = (pubkeyHex: string): string | null => {
        if (pubkeyHex.length < 12) return null;
        const nodeId = pubkeyHex.slice(0, 12).toLowerCase();
        const contact = contacts.find((c) => c.public_key.toLowerCase().startsWith(nodeId));
        const nodeType: NodeType = contact?.type === CONTACT_TYPE_REPEATER ? 'repeater' : 'client';
        addOrUpdateNode(
          nodeId,
          contact?.name || null,
          nodeType,
          false,
          undefined,
          contact?.last_seen
        );
        needsUpdate = true;
        return nodeId;
      };

      const addNodeFromSenderName = (senderName: string): string | null => {
        const senderContact = contacts.find((c) => c.name === senderName);
        if (senderContact) {
          const nodeId = senderContact.public_key.slice(0, 12).toLowerCase();
          const nodeType: NodeType =
            senderContact.type === CONTACT_TYPE_REPEATER ? 'repeater' : 'client';
          addOrUpdateNode(
            nodeId,
            senderContact.name,
            nodeType,
            false,
            undefined,
            senderContact.last_seen
          );
          needsUpdate = true;
          return nodeId;
        }
        const nodeId = `name:${senderName}`;
        addOrUpdateNode(nodeId, senderName, 'client', false);
        needsUpdate = true;
        return nodeId;
      };

      const fullPath: string[] = [];

      if (parsed.payloadType === PayloadType.Advert && parsed.advertPubkey) {
        const srcNodeId = addNodeFromPubkey(parsed.advertPubkey);
        if (srcNodeId) {
          fullPath.push(srcNodeId);
        }
        for (const hexPrefix of parsed.pathBytes) {
          const nodeId = addNodeFromPrefix(hexPrefix, true, showAmbiguousPaths);
          if (nodeId) fullPath.push(nodeId);
        }
        // Always end with self - we received this packet
        if (fullPath.length > 0) {
          fullPath.push('self');
        }
      } else if (parsed.payloadType === PayloadType.TextMessage) {
        if (parsed.srcHash !== null) {
          if (myPubkeyPrefix !== null && parsed.srcHash.toLowerCase() === myPubkeyPrefix) {
            fullPath.push('self');
          } else {
            const srcNodeId = addNodeFromPrefix(parsed.srcHash, false, showAmbiguousNodes);
            if (srcNodeId) fullPath.push(srcNodeId);
          }
        }

        for (const hexPrefix of parsed.pathBytes) {
          const nodeId = addNodeFromPrefix(hexPrefix, true, showAmbiguousPaths);
          if (nodeId) fullPath.push(nodeId);
        }

        if (parsed.dstHash !== null) {
          if (myPubkeyPrefix !== null && parsed.dstHash.toLowerCase() === myPubkeyPrefix) {
            fullPath.push('self');
          } else {
            const dstNodeId = addNodeFromPrefix(parsed.dstHash, false, showAmbiguousNodes);
            if (dstNodeId) fullPath.push(dstNodeId);
            else fullPath.push('self');
          }
        } else {
          fullPath.push('self');
        }
      } else if (parsed.payloadType === PayloadType.GroupText) {
        let srcNodeId: string | null = null;

        if (parsed.groupTextSender) {
          srcNodeId = addNodeFromSenderName(parsed.groupTextSender);
        }
        if (!srcNodeId && packet.decrypted_info?.sender) {
          srcNodeId = addNodeFromSenderName(packet.decrypted_info.sender);
        }

        if (srcNodeId) fullPath.push(srcNodeId);

        for (const hexPrefix of parsed.pathBytes) {
          const nodeId = addNodeFromPrefix(hexPrefix, true, showAmbiguousPaths);
          if (nodeId) fullPath.push(nodeId);
        }

        fullPath.push('self');
      } else {
        for (const hexPrefix of parsed.pathBytes) {
          const nodeId = addNodeFromPrefix(hexPrefix, true, showAmbiguousPaths);
          if (nodeId) fullPath.push(nodeId);
        }
        if (fullPath.length > 0) {
          fullPath.push('self');
        }
      }

      // Safety check: ensure path ends with 'self' since we received this packet
      if (fullPath.length > 0 && fullPath[fullPath.length - 1] !== 'self') {
        fullPath.push('self');
      }

      // Remove consecutive duplicates from path (same node appearing twice in a row)
      const dedupedPath = fullPath.filter((nodeId, i) => i === 0 || nodeId !== fullPath[i - 1]);

      // Create links (immediately for graph updates)
      if (dedupedPath.length >= 2) {
        for (let i = 0; i < dedupedPath.length - 1; i++) {
          // Skip self-links (shouldn't happen but just in case)
          if (dedupedPath[i] === dedupedPath[i + 1]) continue;
          addOrUpdateLink(dedupedPath[i], dedupedPath[i + 1]);
          needsUpdate = true;
        }

        // Generate packet key for aggregation
        const packetKey = generatePacketKey(parsed, packet);
        const packetLabel = getPacketLabel(parsed.payloadType);
        const now = Date.now();

        // Check if we have an existing pending entry for this packet key
        const existing = pendingPacketsRef.current.get(packetKey);

        if (existing && now < existing.expiresAt) {
          // Append path to existing entry (same logical packet via different route)
          existing.paths.push({
            nodes: [...dedupedPath],
            snr: packet.snr ?? null,
            timestamp: now,
          });
        } else {
          // If there was an old expired entry, clean up its timer
          if (packetTimersRef.current.has(packetKey)) {
            clearTimeout(packetTimersRef.current.get(packetKey));
            packetTimersRef.current.delete(packetKey);
          }

          // Create new pending entry
          const originNodeId =
            dedupedPath.length > 0 && dedupedPath[0] !== 'self' ? dedupedPath[0] : null;
          pendingPacketsRef.current.set(packetKey, {
            key: packetKey,
            label: packetLabel,
            originNodeId,
            paths: [
              {
                nodes: [...dedupedPath],
                snr: packet.snr ?? null,
                timestamp: now,
              },
            ],
            firstSeen: now,
            expiresAt: now + OBSERVATION_WINDOW_MS,
          });

          // Set up per-packet timer to publish when observation window ends
          const timer = setTimeout(() => {
            publishPacket(packetKey);
          }, OBSERVATION_WINDOW_MS);
          packetTimersRef.current.set(packetKey, timer);
        }

        // Limit pending entries to prevent memory growth
        if (pendingPacketsRef.current.size > 100) {
          const entries = Array.from(pendingPacketsRef.current.entries());
          const toDelete = entries.sort((a, b) => a[1].firstSeen - b[1].firstSeen).slice(0, 50);
          for (const [key] of toDelete) {
            // Clean up timer when removing entry
            const timer = packetTimersRef.current.get(key);
            if (timer) {
              clearTimeout(timer);
              packetTimersRef.current.delete(key);
            }
            pendingPacketsRef.current.delete(key);
          }
        }

        newAnimated++;
      }
    });

    if (needsUpdate) {
      updateSimulation();
    }

    if (newProcessed > 0) {
      setDebugStats((prev) => ({
        ...prev,
        processed: prev.processed + newProcessed,
        animated: prev.animated + newAnimated,
      }));
    }
  }, [
    packets,
    contacts,
    config,
    showAmbiguousPaths,
    showAmbiguousNodes,
    addOrUpdateNode,
    addOrUpdateLink,
    updateSimulation,
    publishPacket,
  ]);


  // Render function
  const render = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;

    const { width, height } = dimensions;
    const dpr = window.devicePixelRatio || 1;

    // Set canvas size with DPR
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.scale(dpr, dpr);

    // Clear
    ctx.fillStyle = COLORS.background;
    ctx.fillRect(0, 0, width, height);

    // Apply pan and zoom transform
    ctx.save();
    ctx.translate(width / 2, height / 2); // Move origin to center
    ctx.scale(transform.scale, transform.scale);
    ctx.translate(transform.x - width / 2, transform.y - height / 2); // Apply pan offset

    const allNodes = Array.from(nodesMapRef.current.values());
    const allLinks = Array.from(linksMapRef.current.values()).slice(-MAX_LINKS);

    // Filter nodes based on options
    const FORTY_EIGHT_HOURS = 48 * 60 * 60 * 1000;
    const now = Date.now();
    const filteredNodeIds = new Set<string>();

    const nodes = allNodes.filter((node) => {
      // Always show self and non-repeaters
      if (node.type === 'self' || node.type === 'client') {
        filteredNodeIds.add(node.id);
        return true;
      }
      // For repeaters, check the filter
      if (filterOldRepeaters && node.type === 'repeater') {
        // Check lastSeen from contact data, fall back to lastActivity
        const lastTime = node.lastSeen ? node.lastSeen * 1000 : node.lastActivity;
        if (now - lastTime > FORTY_EIGHT_HOURS) {
          return false;
        }
      }
      filteredNodeIds.add(node.id);
      return true;
    });

    // Filter links to only include those between visible nodes
    const links = allLinks.filter((link) => {
      const sourceId = typeof link.source === 'string' ? link.source : link.source.id;
      const targetId = typeof link.target === 'string' ? link.target : link.target.id;
      return filteredNodeIds.has(sourceId) && filteredNodeIds.has(targetId);
    });

    // Draw links - always look up nodes from nodesMapRef for consistent positions
    ctx.strokeStyle = COLORS.link;
    ctx.lineWidth = 2;
    for (const link of links) {
      const sourceId = typeof link.source === 'string' ? link.source : link.source.id;
      const targetId = typeof link.target === 'string' ? link.target : link.target.id;
      const source = nodesMapRef.current.get(sourceId);
      const target = nodesMapRef.current.get(targetId);
      if (source?.x != null && source?.y != null && target?.x != null && target?.y != null) {
        ctx.beginPath();
        ctx.moveTo(source.x, source.y);
        ctx.lineTo(target.x, target.y);
        ctx.stroke();
      }
    }

    // Update and draw particles (only on visible nodes)
    const activeParticles: Particle[] = [];
    for (const particle of particlesRef.current) {
      // Skip particles where either endpoint is filtered out
      if (!filteredNodeIds.has(particle.fromNodeId) || !filteredNodeIds.has(particle.toNodeId)) {
        // Still keep the particle so it can finish if nodes become visible
        particle.progress += particle.speed;
        if (particle.progress <= 1) {
          activeParticles.push(particle);
        }
        continue;
      }

      // Get the actual from/to nodes for correct direction
      const fromNode = nodesMapRef.current.get(particle.fromNodeId);
      const toNode = nodesMapRef.current.get(particle.toNodeId);
      if (fromNode?.x == null || fromNode?.y == null || toNode?.x == null || toNode?.y == null)
        continue;

      // Update progress
      particle.progress += particle.speed;

      // Calculate position along the actual path direction
      const t = particle.progress;

      // Keep particles that haven't finished (including those with negative progress waiting their turn)
      if (t <= 1) {
        activeParticles.push(particle);

        // Only draw if progress is in visible range [0, 1]
        if (t >= 0) {
          const x = fromNode.x + (toNode.x - fromNode.x) * t;
          const y = fromNode.y + (toNode.y - fromNode.y) * t;

          // Glow effect (draw first, behind)
          ctx.fillStyle = particle.color + '40';
          ctx.beginPath();
          ctx.arc(x, y, 14, 0, Math.PI * 2);
          ctx.fill();

          // Draw particle circle
          ctx.fillStyle = particle.color;
          ctx.beginPath();
          ctx.arc(x, y, 10, 0, Math.PI * 2);
          ctx.fill();

          // Draw label text
          ctx.fillStyle = '#ffffff';
          ctx.font = 'bold 8px sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(particle.label, x, y);
        }
      }
    }
    particlesRef.current = activeParticles;

    // Draw nodes
    for (const node of nodes) {
      if (node.x == null || node.y == null) continue;

      // Determine emoji
      let emoji: string;
      if (node.type === 'self') {
        emoji = '🟢';
      } else if (node.type === 'repeater') {
        emoji = '📡';
      } else if (node.isAmbiguous) {
        emoji = '❓';
      } else {
        emoji = '👤'; // Person icon for client nodes
      }

      // Draw emoji - self is 2x bigger
      const emojiSize = node.type === 'self' ? 36 : 18;
      ctx.font = `${emojiSize}px sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(emoji, node.x, node.y);

      // Draw label
      const label = node.isAmbiguous
        ? node.id
        : node.name || (node.type === 'self' ? 'Me' : node.id.slice(0, 8));
      ctx.font = '11px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillStyle = node.isAmbiguous ? COLORS.ambiguous : '#e5e7eb';
      ctx.fillText(label, node.x, node.y + emojiSize / 2 + 4);

      // Draw ambiguous names below
      if (node.isAmbiguous && node.ambiguousNames && node.ambiguousNames.length > 0) {
        ctx.font = '9px sans-serif';
        ctx.fillStyle = '#6b7280';
        let yOffset = node.y + emojiSize / 2 + 18;

        const isHovered = hoveredNodeId === node.id;
        if (isHovered) {
          // Show full list on hover
          for (const name of node.ambiguousNames) {
            ctx.fillText(name, node.x, yOffset);
            yOffset += 11;
          }
        } else if (node.ambiguousNames.length === 1) {
          // Just one name, show it
          ctx.fillText(node.ambiguousNames[0], node.x, yOffset);
        } else {
          // Show first name + count
          const othersCount = node.ambiguousNames.length - 1;
          ctx.fillText(`${node.ambiguousNames[0]} +${othersCount} more`, node.x, yOffset);
        }
      }
    }

    // Restore context after transform
    ctx.restore();
  }, [dimensions, transform, hoveredNodeId, filterOldRepeaters]);

  // Animation loop
  useEffect(() => {
    let running = true;

    const animate = () => {
      if (!running) return;
      render();
      animationFrameRef.current = requestAnimationFrame(animate);
    };

    animate();

    return () => {
      running = false;
      cancelAnimationFrame(animationFrameRef.current);
    };
  }, [render]);

  // Convert screen coordinates to graph coordinates
  const screenToGraph = useCallback(
    (screenX: number, screenY: number) => {
      const { width, height } = dimensions;
      // Reverse the transform: screen -> centered -> unscaled -> unpanned
      const centeredX = screenX - width / 2;
      const centeredY = screenY - height / 2;
      const unscaledX = centeredX / transform.scale;
      const unscaledY = centeredY / transform.scale;
      const graphX = unscaledX - transform.x + width / 2;
      const graphY = unscaledY - transform.y + height / 2;
      return { x: graphX, y: graphY };
    },
    [dimensions, transform]
  );

  // Find node at position
  const findNodeAtPosition = useCallback((graphX: number, graphY: number): GraphNode | null => {
    const nodes = Array.from(nodesMapRef.current.values());
    const hitRadius = 20; // Hit detection radius

    for (const node of nodes) {
      if (node.x == null || node.y == null) continue;
      const dx = graphX - node.x;
      const dy = graphY - node.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < hitRadius) {
        return node;
      }
    }
    return null;
  }, []);

  // Mouse event handlers for pan
  const handleMouseDown = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    isDraggingRef.current = true;
    lastMousePosRef.current = { x: e.clientX, y: e.clientY };
  }, []);

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      const rect = canvas.getBoundingClientRect();
      const screenX = e.clientX - rect.left;
      const screenY = e.clientY - rect.top;

      // Check for node hover (even while dragging, for responsiveness)
      const graphPos = screenToGraph(screenX, screenY);
      const hoveredNode = findNodeAtPosition(graphPos.x, graphPos.y);
      setHoveredNodeId(hoveredNode?.id || null);

      // Handle panning
      if (!isDraggingRef.current) return;

      const dx = e.clientX - lastMousePosRef.current.x;
      const dy = e.clientY - lastMousePosRef.current.y;
      lastMousePosRef.current = { x: e.clientX, y: e.clientY };

      setTransform((prev) => ({
        ...prev,
        x: prev.x + dx / prev.scale,
        y: prev.y + dy / prev.scale,
      }));
    },
    [screenToGraph, findNodeAtPosition]
  );

  const handleMouseUp = useCallback(() => {
    isDraggingRef.current = false;
  }, []);

  const handleMouseLeave = useCallback(() => {
    isDraggingRef.current = false;
    setHoveredNodeId(null);
  }, []);

  // Wheel event handler for zoom (native event for passive: false)
  const handleWheel = useCallback((e: WheelEvent) => {
    e.preventDefault();

    const zoomFactor = 1.1;
    const delta = e.deltaY > 0 ? 1 / zoomFactor : zoomFactor;

    setTransform((prev) => {
      const newScale = Math.min(Math.max(prev.scale * delta, 0.1), 5);
      return {
        ...prev,
        scale: newScale,
      };
    });
  }, []);

  // Attach wheel listener with passive: false to allow preventDefault
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    canvas.addEventListener('wheel', handleWheel, { passive: false });
    return () => {
      canvas.removeEventListener('wheel', handleWheel);
    };
  }, [handleWheel]);

  // Memoize legend items
  const legendItems = useMemo(
    () => [
      { emoji: '🟢', label: 'You', size: 'text-xl' },
      { emoji: '📡', label: 'Repeater', size: 'text-base' },
      { emoji: '👤', label: 'Node', size: 'text-base' },
      { emoji: '❓', label: 'Unknown', size: 'text-base' },
    ],
    []
  );

  // Memoize packet type legend items
  const packetLegendItems = useMemo(
    () => [
      { label: 'AD', color: COLORS.particleAD, description: 'Advertisement' },
      { label: 'GT', color: COLORS.particleGT, description: 'Group Text' },
      { label: 'DM', color: COLORS.particleDM, description: 'Direct Message' },
    ],
    []
  );

  return (
    <div ref={containerRef} className="w-full h-full bg-background relative overflow-hidden">
      <canvas
        ref={canvasRef}
        className="w-full h-full cursor-grab active:cursor-grabbing"
        style={{ display: 'block' }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
      />

      {/* Legend */}
      <div className="absolute bottom-4 left-4 bg-background/80 backdrop-blur-sm rounded-lg p-3 text-xs border border-border">
        <div className="flex gap-6">
          {/* Node legend */}
          <div className="flex flex-col gap-1.5">
            <div className="text-muted-foreground font-medium mb-1">Nodes</div>
            {legendItems.map((item) => (
              <div key={item.label} className="flex items-center gap-2">
                <span className={item.size}>{item.emoji}</span>
                <span>{item.label}</span>
              </div>
            ))}
          </div>
          {/* Packet legend */}
          <div className="flex flex-col gap-1.5">
            <div className="text-muted-foreground font-medium mb-1">Packets</div>
            {packetLegendItems.map((item) => (
              <div key={item.label} className="flex items-center gap-2">
                <div
                  className="w-5 h-5 rounded-full flex items-center justify-center text-[8px] font-bold text-white"
                  style={{ backgroundColor: item.color }}
                >
                  {item.label}
                </div>
                <span>{item.description}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Stats & Options */}
      <div className="absolute top-4 right-4 bg-background/80 backdrop-blur-sm rounded-lg p-3 text-xs border border-border">
        <div className="flex flex-col gap-2">
          <div>Nodes: {debugStats.nodes}</div>
          <div>Links: {debugStats.links}</div>
          <div className="text-muted-foreground">
            Processed: {debugStats.processed} | Animated: {debugStats.animated}
          </div>
          <div className="border-t border-border pt-2 mt-1 flex flex-col gap-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <Checkbox
                checked={showAmbiguousPaths}
                onCheckedChange={(checked) => setShowAmbiguousPaths(checked === true)}
              />
              <span title="Show placeholder nodes for repeaters when the 1-byte prefix matches multiple contacts">
                Ambiguous repeaters
              </span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <Checkbox
                checked={showAmbiguousNodes}
                onCheckedChange={(checked) => setShowAmbiguousNodes(checked === true)}
              />
              <span title="Show placeholder nodes for senders/recipients when only a 1-byte prefix is known">
                Ambiguous sender/recipient
              </span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <Checkbox
                checked={filterOldRepeaters}
                onCheckedChange={(checked) => setFilterOldRepeaters(checked === true)}
              />
              <span title="Only show repeaters heard within the last 48 hours">
                Recent repeaters only
              </span>
            </label>
            <div className="flex flex-col gap-1 mt-1">
              <label
                className="text-muted-foreground"
                title="How strongly nodes repel each other. Higher values spread nodes out more."
              >
                Repulsion: {Math.abs(chargeStrength)}
              </label>
              <input
                type="range"
                min="50"
                max="500"
                value={Math.abs(chargeStrength)}
                onChange={(e) => setChargeStrength(-parseInt(e.target.value))}
                className="w-full h-2 bg-border rounded-lg appearance-none cursor-pointer accent-primary"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
