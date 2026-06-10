/**
 * Minimal shared UI primitives styled with Khata tokens. Keeps every screen
 * visually consistent with the web app's paper/ink ledger look.
 */
import { ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TextInputProps,
  TextProps,
  View,
  ViewProps,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { colors, font, radius, shadow, spacing } from '@/theme/tokens';

export function Screen({
  children,
  scroll = true,
  refreshControl,
}: {
  children: ReactNode;
  scroll?: boolean;
  refreshControl?: React.ReactElement<any>;
}) {
  if (!scroll) {
    return (
      <SafeAreaView style={styles.screen} edges={['top']}>
        {children}
      </SafeAreaView>
    );
  }
  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <ScrollView
        contentContainerStyle={styles.scrollBody}
        refreshControl={refreshControl}
        keyboardShouldPersistTaps="handled"
      >
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

export function AppText({ variant = 'body', style, ...rest }: TextProps & { variant?: keyof typeof textVariants }) {
  return <Text {...rest} style={[textVariants[variant], style]} />;
}

export function Card({ style, children, ...rest }: ViewProps & { children: ReactNode }) {
  return (
    <View {...rest} style={[styles.card, style]}>
      {children}
    </View>
  );
}

export function Button({
  title,
  onPress,
  loading,
  disabled,
  variant = 'primary',
}: {
  title: string;
  onPress: () => void;
  loading?: boolean;
  disabled?: boolean;
  variant?: 'primary' | 'ghost';
}) {
  const isDisabled = disabled || loading;
  return (
    <Pressable
      onPress={onPress}
      disabled={isDisabled}
      style={({ pressed }) => [
        styles.btn,
        variant === 'primary' ? styles.btnPrimary : styles.btnGhost,
        isDisabled && styles.btnDisabled,
        pressed && !isDisabled && styles.btnPressed,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={variant === 'primary' ? '#fff' : colors.primary} />
      ) : (
        <Text style={[styles.btnText, variant === 'ghost' && styles.btnTextGhost]}>{title}</Text>
      )}
    </Pressable>
  );
}

export function Field({ label, ...rest }: TextInputProps & { label: string }) {
  return (
    <View style={{ gap: spacing.xs }}>
      <AppText variant="label">{label}</AppText>
      <TextInput
        placeholderTextColor={colors.inkFaint}
        {...rest}
        style={[styles.input, rest.style]}
      />
    </View>
  );
}

export function Loading() {
  return (
    <View style={styles.center}>
      <ActivityIndicator color={colors.primary} size="large" />
    </View>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <View style={styles.center}>
      <AppText variant="body" style={{ color: colors.neg, textAlign: 'center', marginBottom: spacing.md }}>
        {message}
      </AppText>
      {onRetry && <Button title="Retry" variant="ghost" onPress={onRetry} />}
    </View>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <View style={styles.center}>
      <AppText variant="muted" style={{ textAlign: 'center' }}>
        {message}
      </AppText>
    </View>
  );
}

const textVariants = StyleSheet.create({
  title: { fontSize: font.size.xxl, fontWeight: '700', color: colors.ink },
  heading: { fontSize: font.size.xl, fontWeight: '700', color: colors.ink },
  subhead: { fontSize: font.size.lg, fontWeight: '600', color: colors.ink },
  body: { fontSize: font.size.md, color: colors.ink },
  label: { fontSize: font.size.sm, fontWeight: '600', color: colors.inkSoft },
  muted: { fontSize: font.size.sm, color: colors.inkFaint },
  mono: { fontSize: font.size.lg, fontWeight: '700', color: colors.ink, fontVariant: ['tabular-nums'] },
});

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.paper },
  scrollBody: { padding: spacing.lg, gap: spacing.md },
  card: {
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    padding: spacing.lg,
    ...shadow.card,
  },
  btn: { height: 50, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center', paddingHorizontal: spacing.lg },
  btnPrimary: { backgroundColor: colors.primary },
  btnGhost: { backgroundColor: 'transparent', borderWidth: 1, borderColor: colors.line },
  btnDisabled: { opacity: 0.5 },
  btnPressed: { opacity: 0.85 },
  btnText: { color: '#fff', fontSize: font.size.md, fontWeight: '700' },
  btnTextGhost: { color: colors.primary },
  input: {
    backgroundColor: colors.paper,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    height: 48,
    fontSize: font.size.md,
    color: colors.ink,
  },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl },
});
